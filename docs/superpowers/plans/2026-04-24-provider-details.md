# Provider Details Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an inline expandable details panel to the Providers page showing where each provider scans, what its cleanup recipe does, and what its last scan found.

**Architecture:** Extend the existing `/api/providers` endpoint with optional path/recipe/details fields (no new endpoint). Promote private `_raw_paths` / `_recipe_template` on `PathProvider` to public, extract a `resolve_paths()` helper, add a `details: ClassVar[str | None]` to the base `Provider` class. Frontend joins last-scan stats from the existing `/api/snapshots?kind=auto&limit=1` endpoint and renders the panel as a new full-width grid row beneath each expanded provider row.

**Tech Stack:** Python 3.12 + FastAPI + Pydantic v2 + pytest (backend); React 18 + TypeScript + TanStack Query + Vitest + testing-library (frontend); Tailwind 4 for styling.

**Reference spec:** `docs/superpowers/specs/2026-04-24-provider-details-design.md`

---

## File structure

**New files:**
- `tests/test_path_provider.py` — unit tests for `PathProvider.resolve_paths()`
- `tests/web/test_routes_providers.py` — API shape tests for `/api/providers`
- `web/src/components/ProviderDetailsPanel.tsx` — the details panel component
- `web/tests/unit/ProviderDetailsPanel.test.tsx` — panel tests
- `web/tests/unit/Providers.test.tsx` — integration tests for chevron + expansion

**Modified files:**
- `src/diskdoctor/providers/base.py` — `details` ClassVar, rename `_raw_paths`/`_recipe_template`, add `resolve_paths()`
- `src/diskdoctor/providers/{docker,huggingface,large_files,lm_studio,ollama,venv}.py` — populate `details` ClassVar
- `src/diskdoctor/web/models.py` — four new optional fields on `ProviderInfo`
- `src/diskdoctor/web/routes_scan.py` — populate new fields in `/api/providers` response
- `web/src/hooks/useProviders.ts` — extend `ProviderRow` interface
- `web/src/hooks/useSnapshots.ts` — add `useLatestAutoSnapshot()`
- `web/src/pages/Providers.tsx` — chevron column, expansion state, render panel

---

## Task 1: Promote `_raw_paths` and `_recipe_template` on `PathProvider`

Pure rename. Public-ifies two attributes that the API layer needs to read. No behavior change, no new tests required — existing test suite is the verification.

**Files:**
- Modify: `src/diskdoctor/providers/base.py`

- [ ] **Step 1: Confirm baseline tests pass**

Run: `pytest tests/ -q -x`
Expected: PASS (everything green)

- [ ] **Step 2: Rename in base.py — replace `_raw_paths` → `raw_paths` and `_recipe_template` → `recipe_template`**

In `src/diskdoctor/providers/base.py`, change the four references:

1. Field declarations (~line 92–93):
```python
    raw_paths: tuple[str, ...] = field(default_factory=tuple)
    recipe_template: list[str] = field(default_factory=list)
```

2. `__init__` body (~line 112–113):
```python
        self.raw_paths = raw_paths
        self.recipe_template = recipe_template
```

3. `discover()` body (~line 164):
```python
        for raw in self.raw_paths:
```

4. `discover()` body (~line 173):
```python
                recipe = [line.format(path=quoted) for line in self.recipe_template]
```

- [ ] **Step 3: Verify nothing else references the private names**

Run: `grep -rn "_raw_paths\|_recipe_template" src/ tests/`
Expected: no output (zero remaining references)

- [ ] **Step 4: Run all tests to verify no regression**

Run: `pytest tests/ -q -x`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/diskdoctor/providers/base.py
git commit -m "refactor(providers): promote raw_paths and recipe_template to public on PathProvider"
```

---

## Task 2: Add `Provider.details` ClassVar

A single optional class variable on the base. YAML providers will keep it `None` (their `raw_paths` is the documentation). Class providers populate it in Task 4.

**Files:**
- Modify: `src/diskdoctor/providers/base.py`
- Test: `tests/test_providers_base.py` (existing — extend)

- [ ] **Step 1: Check whether `tests/test_providers_base.py` exists**

Run: `ls tests/test_providers_base.py 2>/dev/null && echo EXISTS || echo MISSING`

If MISSING, create it with this minimal scaffold:

```python
from __future__ import annotations

from diskdoctor.providers.base import Provider


def test_provider_details_defaults_to_none():
    """Subclasses inherit None unless they override."""
    class _Stub(Provider):
        name = "stub"
        description = "x"
        platforms = ("darwin",)
        risk = None  # type: ignore[assignment]

        def discover(self):
            return []

    assert _Stub.details is None
```

(If the file already exists, append the test function above to it.)

- [ ] **Step 2: Run the test — expect failure (`details` not yet on `Provider`)**

Run: `pytest tests/test_providers_base.py::test_provider_details_defaults_to_none -v`
Expected: FAIL with `AttributeError: type object '_Stub' has no attribute 'details'`

- [ ] **Step 3: Add the ClassVar to `Provider`**

In `src/diskdoctor/providers/base.py`, add to the `Provider` class body just after `required_binary` (~line 27):

```python
    details: ClassVar[str | None] = None
```

- [ ] **Step 4: Run the test — expect pass**

Run: `pytest tests/test_providers_base.py::test_provider_details_defaults_to_none -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/diskdoctor/providers/base.py tests/test_providers_base.py
git commit -m "feat(providers): add details ClassVar to Provider base"
```

---

## Task 3: Extract `PathProvider.resolve_paths()` helper

Pull the path-expansion-and-glob-and-existence-filter logic out of `discover()` into a reusable method. The API layer (Task 6) calls it directly to populate `resolved_paths` without sizing or building Entries.

**Files:**
- Modify: `src/diskdoctor/providers/base.py`
- Test: `tests/test_path_provider.py` (new)

- [ ] **Step 1: Write four failing tests**

Create `tests/test_path_provider.py`:

```python
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from diskdoctor.providers.base import PathProvider
from diskdoctor.types import Risk


def _make_provider(raw_paths: tuple[str, ...]) -> PathProvider:
    return PathProvider(
        shell=MagicMock(),
        name="test",
        description="t",
        platforms=("darwin", "linux"),
        risk=Risk.SAFE,
        raw_paths=raw_paths,
        recipe_template=["rm -rf {path}"],
    )


def test_resolve_paths_expands_tilde(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    target = tmp_path / "thing"
    target.mkdir()

    p = _make_provider(("~/thing",))
    resolved = p.resolve_paths()

    assert resolved == [target]


def test_resolve_paths_expands_env_vars(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MY_CACHE", str(tmp_path))
    target = tmp_path / "x"
    target.mkdir()

    p = _make_provider(("$MY_CACHE/x",))
    resolved = p.resolve_paths()

    assert resolved == [target]


def test_resolve_paths_expands_globs(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "c.txt").touch()

    p = _make_provider((f"{tmp_path}/*",))
    resolved = sorted(p.resolve_paths())

    assert resolved == sorted([tmp_path / "a", tmp_path / "b", tmp_path / "c.txt"])


def test_resolve_paths_filters_nonexistent(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()

    p = _make_provider((str(real), str(tmp_path / "missing")))
    resolved = p.resolve_paths()

    assert resolved == [real]
```

- [ ] **Step 2: Run tests — expect failures (`resolve_paths` not defined)**

Run: `pytest tests/test_path_provider.py -v`
Expected: FAIL — `AttributeError: 'PathProvider' object has no attribute 'resolve_paths'`

- [ ] **Step 3: Implement `resolve_paths()` and refactor `discover()` to use it**

In `src/diskdoctor/providers/base.py`, add this method to `PathProvider` (after `available()` and before `discover()`):

```python
    def resolve_paths(self) -> list[Path]:
        """Expand ~, $VARS, and globs in raw_paths; return paths that exist."""
        out: list[Path] = []
        for raw in self.raw_paths:
            expanded = os.path.expanduser(os.path.expandvars(raw))
            matches = glob.glob(expanded) if any(c in expanded for c in "*?[") else [expanded]
            for m in matches:
                p = Path(m)
                if p.exists():
                    out.append(p)
        return out
```

Then refactor `discover()` to call it. Replace the existing loop body with:

```python
    def discover(self) -> list[Entry]:
        entries: list[Entry] = []
        for p in self.resolve_paths():
            size, _skipped = size_path(p)
            quoted = shlex.quote(str(p))
            recipe = [line.format(path=quoted) for line in self.recipe_template]
            try:
                mtime: float | None = p.lstat().st_mtime
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
                    **_stat_kwargs(p),
                )
            )
        return entries
```

(The import for `Path` is already there as `_Path`. The new `resolve_paths` uses `Path` — switch the existing alias to `from pathlib import Path` at the top of the file. Update the existing one usage of `_Path` in `_stat_kwargs(path: _Path)` to `Path` accordingly.)

Concretely, change line 9:
```python
from pathlib import Path
```

And line 55 signature:
```python
def _stat_kwargs(path: Path) -> dict[str, object]:
```

- [ ] **Step 4: Run new tests — expect pass**

Run: `pytest tests/test_path_provider.py -v`
Expected: PASS (4 of 4)

- [ ] **Step 5: Run full suite — verify no regression in `discover()`**

Run: `pytest tests/ -q -x`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/diskdoctor/providers/base.py tests/test_path_provider.py
git commit -m "refactor(providers): extract PathProvider.resolve_paths()"
```

---

## Task 4: Populate `details` ClassVar on the six class providers

Each class provider gets a 1–3 sentence description (≤300 chars). YAML providers stay None. Add a sanity test that asserts every class provider has `details` populated.

**Files:**
- Modify: `src/diskdoctor/providers/docker.py`
- Modify: `src/diskdoctor/providers/huggingface.py`
- Modify: `src/diskdoctor/providers/large_files.py`
- Modify: `src/diskdoctor/providers/lm_studio.py`
- Modify: `src/diskdoctor/providers/ollama.py`
- Modify: `src/diskdoctor/providers/venv.py`
- Test: `tests/test_class_providers_details.py` (new)

- [ ] **Step 1: Write a failing test that asserts each class provider has `details`**

Create `tests/test_class_providers_details.py`:

```python
from __future__ import annotations

from diskdoctor.providers.docker import DockerProvider
from diskdoctor.providers.huggingface import HuggingFaceProvider
from diskdoctor.providers.large_files import LargeFilesProvider
from diskdoctor.providers.lm_studio import LMStudioProvider
from diskdoctor.providers.ollama import OllamaProvider
from diskdoctor.providers.venv import VenvProvider


CLASS_PROVIDERS = [
    DockerProvider,
    HuggingFaceProvider,
    LargeFilesProvider,
    LMStudioProvider,
    OllamaProvider,
    VenvProvider,
]


def test_every_class_provider_has_details_under_300_chars():
    for cls in CLASS_PROVIDERS:
        assert cls.details is not None, f"{cls.__name__} missing details"
        assert isinstance(cls.details, str)
        assert 0 < len(cls.details) <= 300, (
            f"{cls.__name__}.details length {len(cls.details)} not in (0, 300]"
        )
```

- [ ] **Step 2: Run the test — expect failure**

Run: `pytest tests/test_class_providers_details.py -v`
Expected: FAIL — first assertion `OllamaProvider missing details` (or whichever class enumerates first depending on import order, but at least one will fail).

- [ ] **Step 3: Add `details` to each class provider**

For `src/diskdoctor/providers/ollama.py`, add inside the `OllamaProvider` class body, just before `def discover`:

```python
    details = (
        "Models pulled with `ollama pull` live under ~/.ollama/models. "
        "Each model is a few GB; multi-billion-parameter models can exceed 30 GB. "
        "Cleanup uses `ollama rm <name>` per model when the daemon is reachable, "
        "otherwise falls back to deleting the models directory wholesale."
    )
```

For `src/diskdoctor/providers/docker.py`, inside `DockerProvider`:

```python
    details = (
        "Reads `docker system df --format json` and surfaces reclaimable bytes "
        "from images, stopped containers, dangling volumes, and the build cache. "
        "Each category becomes its own entry with the corresponding `docker ... prune` recipe."
    )
```

For `src/diskdoctor/providers/huggingface.py`, inside `HuggingFaceProvider`:

```python
    details = (
        "Scans ~/.cache/huggingface/hub for `models--<user>--<repo>` and "
        "`datasets--<user>--<repo>` directories. Each repo becomes one entry; "
        "cleanup `rm -rf`s the whole repo cache."
    )
```

For `src/diskdoctor/providers/large_files.py`, inside `LargeFilesProvider`:

```python
    details = (
        "Walks ~/Desktop, ~/Documents, ~/Movies, and ~/Pictures looking for "
        "individual files >= 500 MB — typically forgotten ISOs, VM images, "
        "video exports, or backup archives. Each match is advice-only; the recipe "
        "echoes a review prompt rather than running rm."
    )
```

For `src/diskdoctor/providers/lm_studio.py`, inside `LMStudioProvider`:

```python
    details = (
        "Handles LM Studio's two on-disk layouts: legacy `<home>/models/<pub>/<model>/` "
        "and v0.3+ hub manifests under `<home>/hub/models/`. For hub entries, the size "
        "sums the linked HuggingFace cache so the user sees true disk cost."
    )
```

For `src/diskdoctor/providers/venv.py`, inside `VenvProvider`:

```python
    details = (
        "Walks common project roots (~/projects, ~/code, ~/src, etc., up to 6 levels deep) "
        "for directories named .venv / venv / env that contain a pyvenv.cfg marker. "
        "Each venv is one entry; cleanup `rm -rf`s the resolved path."
    )
```

- [ ] **Step 4: Run the sanity test — expect pass**

Run: `pytest tests/test_class_providers_details.py -v`
Expected: PASS

- [ ] **Step 5: Run full suite to verify no regression**

Run: `pytest tests/ -q -x`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/diskdoctor/providers/docker.py \
        src/diskdoctor/providers/huggingface.py \
        src/diskdoctor/providers/large_files.py \
        src/diskdoctor/providers/lm_studio.py \
        src/diskdoctor/providers/ollama.py \
        src/diskdoctor/providers/venv.py \
        tests/test_class_providers_details.py
git commit -m "feat(providers): populate details prose on every class provider"
```

---

## Task 5: Extend `ProviderInfo` and populate it in `/api/providers`

Add four optional fields to the Pydantic model, populate them in the route handler, and lock the contract with API tests.

**Files:**
- Modify: `src/diskdoctor/web/models.py`
- Modify: `src/diskdoctor/web/routes_scan.py`
- Test: `tests/web/test_routes_providers.py` (new)

- [ ] **Step 1: Write three failing API tests**

Create `tests/web/test_routes_providers.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from diskdoctor.providers.base import PathProvider
from diskdoctor.providers.ollama import OllamaProvider
from diskdoctor.types import Risk
from diskdoctor.web.app import build_app
from tests.conftest import FakeShell


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Server with a curated provider list: one YAML, one class (ollama).

    Override `registry.load_providers` so the test is independent of what's
    shipped in paths.yaml. Mirrors the bootstrap used by tests/web/test_routes_scan.py.
    """
    target = tmp_path / "cache"
    target.mkdir()
    shell = FakeShell(which_table={"ollama": "/fake/bin/ollama"})

    yaml_provider = PathProvider(
        shell=shell,
        name="my-yaml",
        description="a yaml-driven provider",
        platforms=("darwin", "linux"),
        risk=Risk.SAFE,
        raw_paths=(str(target), str(tmp_path / "missing")),
        recipe_template=["rm -rf {path}"],
    )
    class_provider = OllamaProvider(shell)

    from diskdoctor import registry

    monkeypatch.setattr(
        registry,
        "load_providers",
        lambda _shell: [yaml_provider, class_provider],
    )

    yaml_file = tmp_path / "paths.yaml"
    yaml_file.write_text("[]\n")
    monkeypatch.setenv("DISKDOCTOR_PATHS_YAML", str(yaml_file))
    (tmp_path / "index.html").write_text("<!doctype html><title>t</title>")

    app = build_app(shell, allowed_hosts={"testserver"}, static_dir=tmp_path)
    return TestClient(app)


def _get_providers(client: TestClient) -> list[dict]:
    r = client.get("/api/providers", headers={"Host": "testserver"})
    assert r.status_code == 200
    return r.json()


def test_yaml_provider_returns_paths_and_recipe(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    rows = _get_providers(client)
    yaml_row = next(r for r in rows if r["name"] == "my-yaml")

    assert isinstance(yaml_row["raw_paths"], list)
    assert len(yaml_row["raw_paths"]) == 2
    assert yaml_row["recipe_template"] == ["rm -rf {path}"]
    # details only set on class providers
    assert yaml_row["details"] is None


def test_class_provider_returns_details_not_paths(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    rows = _get_providers(client)
    class_row = next(r for r in rows if r["name"] == "ollama")

    assert isinstance(class_row["details"], str) and class_row["details"]
    assert class_row["raw_paths"] is None
    assert class_row["resolved_paths"] is None
    assert class_row["recipe_template"] is None


def test_resolved_paths_only_includes_existing(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    rows = _get_providers(client)
    yaml_row = next(r for r in rows if r["name"] == "my-yaml")

    # one of the two raw paths exists (cache), the other is missing
    assert len(yaml_row["resolved_paths"]) == 1
    assert yaml_row["resolved_paths"][0].endswith("cache")
```

- [ ] **Step 2: Run the API tests — expect failures (fields don't exist yet)**

Run: `pytest tests/web/test_routes_providers.py -v`
Expected: FAIL — `KeyError: 'raw_paths'` (or pydantic exclusion of unknown fields gives None, in which case the assertions on lengths/types fail).

- [ ] **Step 3: Add the four optional fields to `ProviderInfo`**

In `src/diskdoctor/web/models.py`, replace the `ProviderInfo` class (~line 18) with:

```python
class ProviderInfo(BaseModel):
    name: str
    description: str
    risk: Literal["safe", "reclaimable", "dangerous"]
    platforms: list[str]
    available: bool
    required_binary: str | None
    kind: Literal["class", "yaml"]
    reason_if_unavailable: str | None = None
    # Provider details — populated per kind. Class providers set `details`;
    # YAML (PathProvider) sets the three path/recipe fields.
    details: str | None = None
    raw_paths: list[str] | None = None
    resolved_paths: list[str] | None = None
    recipe_template: list[str] | None = None
```

- [ ] **Step 4: Populate the new fields in `/api/providers`**

In `src/diskdoctor/web/routes_scan.py`, replace the `providers` route handler (~line 72–89) with:

```python
@router.get("/providers")
def providers(request: Request) -> list[ProviderInfo]:
    providers_list = registry.load_providers(request.app.state.shell)
    out: list[ProviderInfo] = []
    for p in providers_list:
        is_yaml = isinstance(p, PathProvider)
        kind: Literal["class", "yaml"] = "yaml" if is_yaml else "class"
        info = ProviderInfo(
            name=p.name,
            description=p.description,
            risk=p.risk.value,
            platforms=list(p.platforms),
            available=p.available(),
            required_binary=p.required_binary,
            kind=kind,
            details=None if is_yaml else p.details,
            raw_paths=list(p.raw_paths) if is_yaml else None,
            resolved_paths=[str(rp) for rp in p.resolve_paths()] if is_yaml else None,
            recipe_template=list(p.recipe_template) if is_yaml else None,
        )
        out.append(info)
    return out
```

- [ ] **Step 5: Run the API tests — expect pass**

Run: `pytest tests/web/test_routes_providers.py -v`
Expected: PASS (3 of 3)

- [ ] **Step 6: Run full suite to verify no regression**

Run: `pytest tests/ -q -x`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/diskdoctor/web/models.py src/diskdoctor/web/routes_scan.py tests/web/test_routes_providers.py
git commit -m "feat(api): expose provider paths, recipe, and details from /api/providers"
```

---

## Task 6: Frontend types — extend `ProviderRow` and add `useLatestAutoSnapshot`

Hand-update `ProviderRow` (the type used by `Providers.tsx`); the auto-generated `types.gen.ts` will refresh next time `gen:types` runs against a live server. Add a thin TanStack Query hook for the most-recent auto snapshot.

**Files:**
- Modify: `web/src/hooks/useProviders.ts`
- Modify: `web/src/hooks/useSnapshots.ts`
- Test: `web/tests/unit/useLatestAutoSnapshot.test.tsx` (new)

- [ ] **Step 1: Write a failing test for `useLatestAutoSnapshot`**

Create `web/tests/unit/useLatestAutoSnapshot.test.tsx`:

```tsx
import { describe, expect, it, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

const apiFetchMock = vi.fn();
vi.mock("@/api", () => ({
  apiFetch: (path: string) => apiFetchMock(path),
}));

import { useLatestAutoSnapshot } from "@/hooks/useSnapshots";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("useLatestAutoSnapshot", () => {
  beforeEach(() => apiFetchMock.mockReset());

  it("requests the newest auto snapshot and returns the single meta", async () => {
    apiFetchMock.mockResolvedValue([
      {
        name: "2026-04-24--auto.json",
        path: "/x/a.json",
        scanned_at: "2026-04-24T00:00:00Z",
        hostname: "h",
        platform: "darwin",
        note: null,
        total_bytes: 100,
        kind: "auto",
        duration_ms: 1234,
        entry_count: 10,
        per_provider: [{ name: "ollama", bytes: 100, entries: 1, duration_ms: 50 }],
      },
    ]);

    const { result } = renderHook(() => useLatestAutoSnapshot(), { wrapper });
    await waitFor(() => expect(result.current.data).toBeDefined());

    expect(apiFetchMock).toHaveBeenCalledWith("/snapshots?kind=auto&limit=1");
    expect(result.current.data?.duration_ms).toBe(1234);
  });

  it("returns null when no auto snapshots exist", async () => {
    apiFetchMock.mockResolvedValue([]);

    const { result } = renderHook(() => useLatestAutoSnapshot(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data).toBeNull();
  });
});
```

- [ ] **Step 2: Run the test — expect failure**

Run: `cd web && npx vitest run tests/unit/useLatestAutoSnapshot.test.tsx`
Expected: FAIL — `useLatestAutoSnapshot is not exported from "@/hooks/useSnapshots"`.

- [ ] **Step 3: Add `useLatestAutoSnapshot` to `useSnapshots.ts`**

Append to `web/src/hooks/useSnapshots.ts` (after `useCreateSnapshot`):

```ts
export function useLatestAutoSnapshot() {
  return useQuery({
    queryKey: ["snapshots", "latest-auto"],
    queryFn: async () => {
      const list = await apiFetch<SnapshotMeta[]>("/snapshots?kind=auto&limit=1");
      return list[0] ?? null;
    },
    staleTime: 30_000,
  });
}
```

- [ ] **Step 4: Run test — expect pass**

Run: `cd web && npx vitest run tests/unit/useLatestAutoSnapshot.test.tsx`
Expected: PASS (2 of 2)

- [ ] **Step 5: Extend `ProviderRow` with the new fields**

Replace `web/src/hooks/useProviders.ts` with:

```ts
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api";

export interface ProviderRow {
  name: string;
  description: string;
  risk: "safe" | "reclaimable" | "dangerous";
  platforms: string[];
  available: boolean;
  required_binary: string | null;
  kind: "class" | "yaml";
  // New: details panel data. All optional — populated based on `kind`.
  details: string | null;
  raw_paths: string[] | null;
  resolved_paths: string[] | null;
  recipe_template: string[] | null;
}

export function useProviders() {
  return useQuery({
    queryKey: ["providers"],
    queryFn: () => apiFetch<ProviderRow[]>("/providers"),
    staleTime: 60_000,
  });
}
```

- [ ] **Step 6: Run frontend test suite to verify no type/test regression**

Run: `cd web && npm test`
Expected: PASS (all existing tests + the two new ones)

- [ ] **Step 7: Run TypeScript build to confirm types compile**

Run: `cd web && npx tsc --noEmit`
Expected: clean (no errors)

- [ ] **Step 8: Commit**

```bash
git add web/src/hooks/useProviders.ts web/src/hooks/useSnapshots.ts web/tests/unit/useLatestAutoSnapshot.test.tsx
git commit -m "feat(web): add useLatestAutoSnapshot hook and extend ProviderRow"
```

---

## Task 7: Build `<ProviderDetailsPanel>` component

The panel that renders inside an expanded row. Three optional sections: paths (raw → resolved listing for YAML, prose for class), cleanup recipe (YAML only), last-scan stats (both kinds when an auto snapshot exists).

**Files:**
- Create: `web/src/components/ProviderDetailsPanel.tsx`
- Test: `web/tests/unit/ProviderDetailsPanel.test.tsx`

- [ ] **Step 1: Write the failing component test**

Create `web/tests/unit/ProviderDetailsPanel.test.tsx`:

```tsx
import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { ProviderDetailsPanel } from "@/components/ProviderDetailsPanel";
import type { ProviderRow } from "@/hooks/useProviders";

function classProvider(): ProviderRow {
  return {
    name: "ollama",
    description: "Ollama local LLM models",
    risk: "reclaimable",
    platforms: ["darwin", "linux"],
    available: true,
    required_binary: "ollama",
    kind: "class",
    details: "Models pulled with `ollama pull` live under ~/.ollama/models.",
    raw_paths: null,
    resolved_paths: null,
    recipe_template: null,
  };
}

function yamlProvider(): ProviderRow {
  return {
    name: "my-yaml",
    description: "yaml driven",
    risk: "safe",
    platforms: ["darwin"],
    available: true,
    required_binary: null,
    kind: "yaml",
    details: null,
    raw_paths: ["~/cache/foo", "~/missing"],
    resolved_paths: ["/Users/me/cache/foo"],
    recipe_template: ["rm -rf {path}", "echo done"],
  };
}

describe("ProviderDetailsPanel", () => {
  it("renders details prose for a class provider", () => {
    render(<ProviderDetailsPanel provider={classProvider()} lastAuto={null} />);
    expect(screen.getByText(/Ollama pull/i)).toBeInTheDocument();
    // No recipe section when recipe_template is null
    expect(screen.queryByText(/cleanup recipe/i)).not.toBeInTheDocument();
  });

  it("renders raw and resolved paths for a yaml provider", () => {
    render(<ProviderDetailsPanel provider={yamlProvider()} lastAuto={null} />);
    expect(screen.getByText("~/cache/foo")).toBeInTheDocument();
    expect(screen.getByText("/Users/me/cache/foo")).toBeInTheDocument();
    // The unresolved one is shown with a (no match) marker
    expect(screen.getByText("~/missing")).toBeInTheDocument();
    expect(screen.getByText(/no match/i)).toBeInTheDocument();
  });

  it("renders the recipe template verbatim with {path} preserved", () => {
    render(<ProviderDetailsPanel provider={yamlProvider()} lastAuto={null} />);
    const code = screen.getByTestId("recipe-block");
    expect(within(code).getByText(/rm -rf \{path\}/)).toBeInTheDocument();
    expect(within(code).getByText(/echo done/)).toBeInTheDocument();
  });

  it("omits last-scan section when lastAuto is null", () => {
    render(<ProviderDetailsPanel provider={classProvider()} lastAuto={null} />);
    expect(screen.queryByText(/last scan/i)).not.toBeInTheDocument();
  });

  it("renders last-scan stats when lastAuto is provided", () => {
    render(
      <ProviderDetailsPanel
        provider={classProvider()}
        lastAuto={{ name: "ollama", bytes: 5_000_000_000, entries: 3, duration_ms: 1200 }}
      />,
    );
    expect(screen.getByText(/last scan/i)).toBeInTheDocument();
    expect(screen.getByText(/entries:\s*3/i)).toBeInTheDocument();
    // Bytes are formatted via existing humaniser; just check the number is present
    expect(screen.getByText(/1\.2s|1200/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the test — expect failure (component doesn't exist)**

Run: `cd web && npx vitest run tests/unit/ProviderDetailsPanel.test.tsx`
Expected: FAIL — `Cannot find module '@/components/ProviderDetailsPanel'`.

- [ ] **Step 3: Implement the component**

Create `web/src/components/ProviderDetailsPanel.tsx`:

```tsx
import type { ProviderRow } from "@/hooks/useProviders";
import type { ProviderTimingMeta } from "@/hooks/useSnapshots";
import { formatBytes } from "@/lib/format";
import { formatMs } from "@/lib/format";

interface Props {
  provider: ProviderRow;
  lastAuto: ProviderTimingMeta | null;
}

export function ProviderDetailsPanel({ provider, lastAuto }: Props) {
  return (
    <div
      role="region"
      aria-label={`${provider.name} details`}
      className="bg-surface-muted px-4 py-3 space-y-3"
    >
      <PathsSection provider={provider} />
      {provider.recipe_template && <RecipeSection lines={provider.recipe_template} />}
      {lastAuto && <LastScanSection stats={lastAuto} />}
    </div>
  );
}

function SectionHeading({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-[9.5px] uppercase tracking-widest text-text-dim mb-1">{children}</div>
  );
}

function PathsSection({ provider }: { provider: ProviderRow }) {
  if (provider.raw_paths && provider.raw_paths.length > 0) {
    const resolvedSet = new Set(provider.resolved_paths ?? []);
    return (
      <div>
        <SectionHeading>paths</SectionHeading>
        <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,2fr)] gap-x-4 gap-y-1">
          {provider.raw_paths.map((raw) => {
            // Resolved entries that match this raw path: anything whose
            // expanded form equals or is a child of the raw path. We keep
            // it simple — if any resolved path doesn't match any other raw,
            // show it under the first raw whose prefix matches.
            const matched = (provider.resolved_paths ?? []).filter((rp) =>
              matchesRaw(raw, rp),
            );
            const matchedDeduped = matched.filter((rp) => resolvedSet.has(rp));
            return (
              <RowPair
                key={raw}
                raw={raw}
                resolved={matchedDeduped.length > 0 ? matchedDeduped : null}
              />
            );
          })}
        </div>
      </div>
    );
  }
  if (provider.details) {
    return (
      <div>
        <SectionHeading>paths</SectionHeading>
        <p className="text-text-muted text-[11px] leading-relaxed">{provider.details}</p>
      </div>
    );
  }
  return (
    <div>
      <SectionHeading>paths</SectionHeading>
      <p className="text-text-dim text-[11px]">No path information available.</p>
    </div>
  );
}

function RowPair({ raw, resolved }: { raw: string; resolved: string[] | null }) {
  return (
    <>
      <div className="font-mono text-text-muted truncate" title={raw}>
        {raw}
      </div>
      <div className="font-mono text-text-dim">
        {resolved === null ? (
          <span className="text-text-dim italic">(no match)</span>
        ) : (
          resolved.map((r) => (
            <div key={r} className="truncate" title={r}>
              {r}
            </div>
          ))
        )}
      </div>
    </>
  );
}

function matchesRaw(raw: string, resolved: string): boolean {
  // Cheap heuristic: if raw has no glob/var marker, the resolved path
  // matches when it equals the home-expanded raw OR ends with raw's tail.
  // Good enough for displaying — the backend has the exact mapping.
  const tail = raw.replace(/^[~$][^/]*\/?/, "");
  return resolved.endsWith(tail) || resolved === raw;
}

function RecipeSection({ lines }: { lines: string[] }) {
  return (
    <div>
      <SectionHeading>cleanup recipe</SectionHeading>
      <p className="text-text-dim text-[10px] mb-1">
        Runs once per matched path, with <code>{"{path}"}</code> replaced by the resolved path.
      </p>
      <pre
        data-testid="recipe-block"
        className="bg-surface-sunken font-mono text-[11px] p-2 rounded overflow-x-auto"
      >
        <code>{lines.join("\n")}</code>
      </pre>
    </div>
  );
}

function LastScanSection({ stats }: { stats: ProviderTimingMeta }) {
  return (
    <div>
      <SectionHeading>last scan</SectionHeading>
      <div className="text-text-muted text-[11px] flex gap-4">
        <span>entries: {stats.entries}</span>
        <span>total: {formatBytes(stats.bytes)}</span>
        <span>duration: {formatMs(stats.duration_ms)}</span>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Confirm `formatBytes` and `formatMs` exist in `@/lib/format`**

Run: `grep -n "export.*formatBytes\|export.*formatMs" web/src/lib/format.ts`
Expected: both functions are exported.

If `formatBytes` does not exist (only `formatMs` does), use the project's existing bytes formatter — search for it:

```bash
grep -rn "function format.*Bytes\|export.*format.*Bytes" web/src/ | head -5
```

If found at a different path, update the import in `ProviderDetailsPanel.tsx` to match. If no such helper exists, add one to `web/src/lib/format.ts`:

```ts
export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let v = n / 1024;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(1)} ${units[i]}`;
}
```

- [ ] **Step 5: Run the panel tests — expect pass**

Run: `cd web && npx vitest run tests/unit/ProviderDetailsPanel.test.tsx`
Expected: PASS (5 of 5)

- [ ] **Step 6: Commit**

```bash
git add web/src/components/ProviderDetailsPanel.tsx \
        web/tests/unit/ProviderDetailsPanel.test.tsx \
        web/src/lib/format.ts  # only if you had to add formatBytes
git commit -m "feat(web): ProviderDetailsPanel component with paths/recipe/last-scan sections"
```

---

## Task 8: Wire chevron column and expansion state into `Providers.tsx`

Add a leading 24px chevron column. Track expanded rows in a `Set<string>`. Render `<ProviderDetailsPanel>` as a full-width grid row immediately below each expanded provider row.

**Files:**
- Modify: `web/src/pages/Providers.tsx`
- Test: `web/tests/unit/Providers.test.tsx` (new)

- [ ] **Step 1: Write failing integration tests**

Create `web/tests/unit/Providers.test.tsx`:

```tsx
import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

vi.mock("@/api", () => ({
  apiFetch: vi.fn((path: string) => {
    if (path.startsWith("/providers")) {
      return Promise.resolve([
        {
          name: "ollama",
          description: "ollama models",
          risk: "reclaimable",
          platforms: ["darwin", "linux"],
          available: true,
          required_binary: "ollama",
          kind: "class",
          details: "Models live under ~/.ollama/models.",
          raw_paths: null,
          resolved_paths: null,
          recipe_template: null,
        },
        {
          name: "my-yaml",
          description: "yaml provider",
          risk: "safe",
          platforms: ["darwin"],
          available: true,
          required_binary: null,
          kind: "yaml",
          details: null,
          raw_paths: ["~/cache/foo"],
          resolved_paths: ["/Users/me/cache/foo"],
          recipe_template: ["rm -rf {path}"],
        },
      ]);
    }
    if (path.startsWith("/snapshots")) {
      return Promise.resolve([]);
    }
    if (path === "/disk-usage") {
      return Promise.resolve({ total: 1, used: 0, free: 1 });
    }
    return Promise.resolve(null);
  }),
}));

import Providers from "@/pages/Providers";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={client}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  );
}

describe("Providers page — details expansion", () => {
  it("starts with no rows expanded and aria-expanded=false on chevrons", async () => {
    render(<Providers />, { wrapper });
    const chevrons = await screen.findAllByRole("button", { name: /show details/i });
    expect(chevrons.length).toBe(2);
    chevrons.forEach((c) => expect(c).toHaveAttribute("aria-expanded", "false"));
  });

  it("clicking the chevron expands that row's details panel", async () => {
    const user = userEvent.setup();
    render(<Providers />, { wrapper });
    const chevron = await screen.findByRole("button", { name: /show details for ollama/i });
    await user.click(chevron);

    expect(chevron).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("region", { name: /ollama details/i })).toBeInTheDocument();
  });

  it("supports expanding more than one row at a time", async () => {
    const user = userEvent.setup();
    render(<Providers />, { wrapper });
    await user.click(await screen.findByRole("button", { name: /show details for ollama/i }));
    await user.click(await screen.findByRole("button", { name: /show details for my-yaml/i }));

    expect(screen.getByRole("region", { name: /ollama details/i })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: /my-yaml details/i })).toBeInTheDocument();
  });

  it("collapsing removes the panel from the DOM", async () => {
    const user = userEvent.setup();
    render(<Providers />, { wrapper });
    const chevron = await screen.findByRole("button", { name: /show details for ollama/i });
    await user.click(chevron);
    await user.click(chevron); // second click collapses

    expect(chevron).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("region", { name: /ollama details/i })).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the tests — expect failure (chevron doesn't exist)**

Run: `cd web && npx vitest run tests/unit/Providers.test.tsx`
Expected: FAIL — no element matching `name: /show details/i`.

- [ ] **Step 3: Modify `Providers.tsx`**

Replace `web/src/pages/Providers.tsx` with the version below. Changes from current:
- Adds `useState<Set<string>>` for `expandedRows`
- Adds `useLatestAutoSnapshot()` and builds a `Map<string, ProviderTimingMeta>` keyed by provider name
- Prepends a 24px chevron column to both the header row and each data row
- Renders `<ProviderDetailsPanel>` as a full-width grid row right after each expanded row

```tsx
import { useMemo, useState } from "react";
import { useProviders, type ProviderRow } from "@/hooks/useProviders";
import { useSelectedProviders } from "@/hooks/useSelectedProviders";
import { useLatestAutoSnapshot, type ProviderTimingMeta } from "@/hooks/useSnapshots";
import { RiskBadge } from "@/components/RiskBadge";
import { DiskUsageBar } from "@/components/DiskUsageBar";
import { ProviderIcon } from "@/components/ProviderIcon";
import { ProviderDetailsPanel } from "@/components/ProviderDetailsPanel";

const GRID_COLS = "24px 60px 20px 1.3fr 0.8fr 1fr 0.6fr 0.9fr";

export default function Providers() {
  const { data, isLoading, error } = useProviders();
  const { isEnabled, setEnabled, setMany } = useSelectedProviders();
  const { data: lastAutoSnapshot } = useLatestAutoSnapshot();
  const [query, setQuery] = useState("");
  const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set());

  const providers = useMemo(() => data ?? [], [data]);

  const lastByProvider = useMemo<Map<string, ProviderTimingMeta>>(() => {
    const m = new Map<string, ProviderTimingMeta>();
    for (const t of lastAutoSnapshot?.per_provider ?? []) {
      m.set(t.name, t);
    }
    return m;
  }, [lastAutoSnapshot]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return providers;
    return providers.filter(
      (p) =>
        p.name.toLowerCase().includes(q) ||
        p.description.toLowerCase().includes(q),
    );
  }, [providers, query]);

  const enabledCount = providers.filter((p) => isEnabled(p.name)).length;
  const allOn = providers.length > 0 && enabledCount === providers.length;
  const allOff = enabledCount === 0;
  const mixed = !allOn && !allOff;

  function flipMaster() {
    const names = providers.map((p) => p.name);
    setMany(names, allOff);
  }

  function toggleExpanded(name: string) {
    setExpandedRows((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }

  if (isLoading)
    return <div className="p-8 text-text-muted font-mono text-sm">loading…</div>;
  if (error)
    return <div className="p-8 text-risk-danger font-mono text-sm">{String(error)}</div>;

  return (
    <div className="font-mono text-[11px]">
      <header className="px-6 pt-6 pb-3 flex items-center justify-between gap-4 flex-wrap">
        <label className="relative block w-full max-w-[360px] flex-1 min-w-[260px]">
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search providers by name or description…"
            className="w-full bg-bg-elev-1 border border-border rounded pl-7 pr-8 py-1.5 text-[11px] text-text placeholder:text-text-muted focus:outline-none focus:border-risk-reclaim"
          />
          <span className="absolute left-2 top-1/2 -translate-y-1/2 text-text-muted pointer-events-none">
            ⌕
          </span>
          {query && (
            <button
              onClick={() => setQuery("")}
              aria-label="Clear search"
              className="absolute right-2 top-1/2 -translate-y-1/2 text-text-muted hover:text-text"
            >
              ✕
            </button>
          )}
        </label>

        <div className="text-text-dim text-[11px] tabular-nums">
          <b className="text-text">{enabledCount}</b> of{" "}
          <b className="text-text">{providers.length}</b> enabled
          {query && (
            <span className="text-text-muted">
              {" "}
              · {filtered.length} match{filtered.length === 1 ? "" : "es"}
            </span>
          )}
        </div>

        <div className="flex items-center gap-2">
          <span className="text-text-muted text-[10px]">
            {allOff ? "enable all" : "disable all"}
          </span>
          <button
            type="button"
            onClick={flipMaster}
            aria-pressed={!allOff}
            aria-label={allOff ? "Enable all providers" : "Disable all providers"}
            disabled={providers.length === 0}
            className={`w-[36px] h-[18px] rounded-full relative transition-colors ${
              allOn ? "bg-[#2a7f55]" : mixed ? "bg-[#2a7f55]/50" : "bg-bg-control-off"
            }`}
          >
            <span
              className={`absolute top-[2px] w-[14px] h-[14px] rounded-full bg-white transition-all ${
                allOff ? "left-[2px] bg-text-muted" : "right-[2px]"
              }`}
            />
          </button>
        </div>
        <DiskUsageBar />
      </header>

      <div className="px-6 pb-3 text-text-muted text-[10px]">
        Toggle off to exclude a provider from scans. Preference is stored locally.
      </div>

      <div className="px-6">
        <div
          className="grid gap-3 px-3 py-2 text-[9.5px] uppercase tracking-widest text-text-muted border-b border-border"
          style={{ gridTemplateColumns: GRID_COLS }}
        >
          <div aria-hidden="true" />
          <div>enabled</div>
          <div aria-hidden="true" />
          <div>name</div>
          <div>risk</div>
          <div>platforms</div>
          <div>available</div>
          <div>required binary</div>
        </div>
        {filtered.length === 0 ? (
          <div className="p-8 text-center text-text-dim">
            {query ? (
              <>
                No providers match <span className="text-text">&ldquo;{query}&rdquo;</span>.
              </>
            ) : (
              "No providers."
            )}
          </div>
        ) : (
          filtered.map((p) => (
            <ProviderRowView
              key={p.name}
              provider={p}
              query={query}
              isOn={isEnabled(p.name)}
              isExpanded={expandedRows.has(p.name)}
              lastAuto={lastByProvider.get(p.name) ?? null}
              onToggleEnabled={() => setEnabled(p.name, !isEnabled(p.name))}
              onToggleExpanded={() => toggleExpanded(p.name)}
            />
          ))
        )}
      </div>
    </div>
  );
}

interface RowProps {
  provider: ProviderRow;
  query: string;
  isOn: boolean;
  isExpanded: boolean;
  lastAuto: ProviderTimingMeta | null;
  onToggleEnabled: () => void;
  onToggleExpanded: () => void;
}

function ProviderRowView({
  provider: p,
  query,
  isOn,
  isExpanded,
  lastAuto,
  onToggleEnabled,
  onToggleExpanded,
}: RowProps) {
  return (
    <>
      <div
        className="grid gap-3 px-3 py-2 items-center border-b border-border-subtle hover:bg-bg-elev-1"
        style={{ gridTemplateColumns: GRID_COLS }}
      >
        <button
          type="button"
          onClick={onToggleExpanded}
          aria-expanded={isExpanded}
          aria-label={`${isExpanded ? "Hide" : "Show"} details for ${p.name}`}
          className="text-text-muted hover:text-text w-[20px] h-[20px] flex items-center justify-center"
        >
          <svg
            aria-hidden="true"
            width="10"
            height="10"
            viewBox="0 0 10 10"
            className={`transition-transform ${isExpanded ? "rotate-90" : ""}`}
          >
            <path d="M3 1 L7 5 L3 9" stroke="currentColor" strokeWidth="1.5" fill="none" />
          </svg>
        </button>
        <button
          type="button"
          onClick={onToggleEnabled}
          aria-pressed={isOn}
          aria-label={`Toggle ${p.name}`}
          className={`w-[30px] h-[16px] rounded-full relative transition-colors ${
            isOn ? "bg-[#2a7f55]" : "bg-bg-control-off"
          }`}
        >
          <span
            className={`absolute top-[2px] w-[12px] h-[12px] rounded-full bg-white transition-all ${
              isOn ? "right-[2px]" : "left-[2px] bg-text-muted"
            }`}
          />
        </button>
        <div className="flex items-center justify-center">
          <ProviderIcon
            slug={p.name}
            size={16}
            className={isOn ? "text-text" : "text-text-muted"}
          />
        </div>
        <div>
          <div className={`font-medium ${isOn ? "text-text" : "text-text-muted"}`}>
            <Highlight text={p.name} query={query} />
          </div>
          <div className="text-text-muted text-[10px] mt-px">
            <Highlight text={p.description} query={query} />
          </div>
        </div>
        <div>
          <RiskBadge risk={p.risk} />
        </div>
        <div className="text-text-dim">{p.platforms.join(", ")}</div>
        <div>
          <span
            className={`inline-block w-2 h-2 rounded-full ${
              p.available ? "bg-risk-safe shadow-[0_0_6px_var(--risk-safe)]" : "bg-text-muted"
            }`}
          />
          <span className="ml-2 text-text-dim">{p.available ? "yes" : "no"}</span>
        </div>
        <div className="text-text-muted">{p.required_binary ?? "—"}</div>
      </div>
      {isExpanded && (
        <div
          className="border-b border-border-subtle"
          style={{ gridColumn: "1 / -1" }}
        >
          <ProviderDetailsPanel provider={p} lastAuto={lastAuto} />
        </div>
      )}
    </>
  );
}

function Highlight({ text, query }: { text: string; query: string }) {
  const q = query.trim();
  if (!q) return <>{text}</>;
  const idx = text.toLowerCase().indexOf(q.toLowerCase());
  if (idx < 0) return <>{text}</>;
  return (
    <>
      {text.slice(0, idx)}
      <mark className="bg-risk-reclaim/30 text-text rounded-[2px] px-[1px]">
        {text.slice(idx, idx + q.length)}
      </mark>
      {text.slice(idx + q.length)}
    </>
  );
}
```

- [ ] **Step 4: Install `@testing-library/user-event` if not present**

Run: `cd web && npx vitest --version >/dev/null && grep -q '"@testing-library/user-event"' package.json && echo HAVE || echo MISSING`
Expected: `HAVE`. If `MISSING`, install: `cd web && npm install --save-dev @testing-library/user-event`.

- [ ] **Step 5: Run the page tests — expect pass**

Run: `cd web && npx vitest run tests/unit/Providers.test.tsx`
Expected: PASS (4 of 4)

- [ ] **Step 6: Run the full frontend suite to verify no regression**

Run: `cd web && npm test`
Expected: PASS

- [ ] **Step 7: Run TypeScript build**

Run: `cd web && npx tsc --noEmit`
Expected: clean

- [ ] **Step 8: Commit**

```bash
git add web/src/pages/Providers.tsx web/tests/unit/Providers.test.tsx web/package.json web/package-lock.json
git commit -m "feat(web): expandable provider details on Providers page"
```

(Drop `package.json`/`package-lock.json` from `git add` if you didn't have to install user-event.)

---

## Task 9: End-to-end verification

After all per-task tests pass, do a one-shot smoke check before merging.

**Files:** none (verification only)

- [ ] **Step 1: Run the entire backend suite**

Run: `pytest tests/ -q`
Expected: PASS, no collection errors.

- [ ] **Step 2: Run the entire frontend suite**

Run: `cd web && npm test`
Expected: PASS.

- [ ] **Step 3: Run the frontend type check**

Run: `cd web && npx tsc --noEmit`
Expected: clean.

- [ ] **Step 4: Build the SPA bundle to confirm production build works**

Run: `cd web && npm run build`
Expected: vite reports a successful build, writes files under `src/diskdoctor/web/_static/dist/`.

- [ ] **Step 5: (Optional, manual) Smoke test in the browser**

Run: `./scripts/deploy.sh`

Then open the served URL, go to Providers, click a chevron on a YAML provider — confirm raw/resolved paths and recipe show. Click a class provider's chevron — confirm details prose renders. Run a scan, then re-open the panel — confirm "last scan" stats appear.

This is a sanity check; failure here means the integration with the live backend has a defect not caught by unit tests.

---

## Notes on YAGNI / DRY adherence

- **No new endpoint** — `/api/providers` already exists; we only widen its response.
- **No persistence of expansion state** — explicit non-goal in spec; users haven't asked for it.
- **No deep-link, no per-provider dedicated route** — the inline panel is the entire UX.
- **`details` is a single ClassVar string, not a structured object** — simplest thing that works for the six current class providers.
- **`resolve_paths()` is the only new method on `PathProvider`** — `discover()` now consumes it, which is the DRY win that justifies the refactor.
- **Last-scan stats reuse `/api/snapshots?kind=auto&limit=1`** — no duplication of telemetry storage.

## Risk register

- **Filesystem I/O on every `/api/providers` call** — `available()` already touches disk, so this is consistent. Profile if it shows up later.
- **`matchesRaw` heuristic in `ProviderDetailsPanel`** — the resolved-paths-to-raw-paths mapping is approximate. If users complain, the API can return a `list[tuple[raw, resolved[]]]` structure later.
- **Grid layout depends on Providers page staying a CSS grid** — if it ever becomes a `<table>`, the full-width-row trick (`gridColumn: 1 / -1`) needs to become `colSpan`. Documented in spec §9.
