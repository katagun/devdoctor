# Agent Session Stores Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Offer Codex and Claude Code transcripts by age bucket, never wholesale, and size OpenCode's database with read-only session counts.

**Architecture:** One module, `devdoctor/providers/agent_sessions.py`, holds a shared `bucket_entries` helper (records in, one entry per fixed age bucket out) and three providers that only differ in how they enumerate session records. The cleanup path, filters and web UI are untouched except for a count in the web recipe hint.

**Tech Stack:** Python 3.12, `os.walk`/`lstat`, `sqlite3` read-only URI, the existing `sizer.size_many` and `Entry`/`DiskUsage` types; Vitest for the one web change.

**Spec:** `docs/superpowers/specs/2026-09-24-agent-sessions-design.md`

## Global Constraints

- Retention floor default **90 days**, env `DEVDOCTOR_SESSION_RETENTION_DAYS`, clamped to **30** minimum.
- Bucket edges fixed at **0/30/90/180/365** days; ids `<provider>:<lower>-<upper>d` and `<provider>:365d+`.
- A bucket's `mtime` is its **newest** member; younger-than-floor buckets are `dangerous` with one `AdviceAction`; others `reclaimable` with one `DeletePathAction` per member path.
- SQLite stores are **never written**; reads use `file:<path>?mode=ro`.
- `~/.claude/projects/<slug>/memory/` and non-UUID names are never records.
- No new CLI flags; no web page changes.

Decision taken at execution: the spec's three-PR rollout became one PR, because the three providers share one module and one test file and are each under 60 lines.

---

### Task 1: The bucket helper and the three providers

**Files:**
- Create: `src/devdoctor/providers/agent_sessions.py`
- Modify: `src/devdoctor/registry.py` (import the three classes; add them to `_CLASS_PROVIDERS`)
- Test: `tests/test_agent_sessions.py`

**Interfaces:**
- Produces: `retention_floor_days() -> int`; `SessionRecord(paths: tuple[Path, ...], mtime: float, size_bytes: int)`; `bucket_entries(provider, root, records, *, title, noun="sessions", now=None) -> list[Entry]`; `CodexSessionsProvider`, `ClaudeCodeSessionsProvider`, `OpenCodeSessionsProvider` (all `Provider` subclasses, family `agent-sessions`).

- [x] **Step 1: Write the failing tests** — the file `tests/test_agent_sessions.py` as committed: floor defaults and clamp; bucket edges at 89.5 vs 90.5 days with ids, labels, actions, sizes and newest-member `mtime`; a raised floor moving only the risk boundary; Codex fixture with a stray file, a symlink and SQLite indexes; Claude Code transcript plus dated sibling directory with `memory/` untouched; OpenCode `sqlite3` fixture counted read-only and an unreadable file still sized; registry family; `clean --older-than 90d` removing two old files one `rm -f` each; `--allow-dangerous` executing nothing for a young bucket.
- [x] **Step 2: Run them** — `uv run pytest tests/test_agent_sessions.py -q`, expected import error.
- [x] **Step 3: Implement** — the module as committed (see the file; every function is documented there).
- [x] **Step 4: Run them** — 11 passed.
- [x] **Step 5: Commit** with the docs of Task 3.

### Task 2: Web recipe hint counts further commands

**Files:**
- Modify: `web/src/hooks/useScan.ts` (`recipeHint(recipe)` helper)
- Test: `web/tests/unit/useScan.test.tsx`

- [x] **Step 1: Failing test** — an entry with three `rm -f` lines gets `"rm -f -- /a (+2 more)"`; an entry whose first line is `echo '...'` keeps its text.
- [x] **Step 2: Implement** — `recipeHint` appends ` (+N more)` when `recipe.length > 1` and the first line is not advice.
- [x] **Step 3: `cd web && bun run vitest run tests/unit/useScan.test.tsx`** — passes.

### Task 3: Docs

**Files:**
- Modify: `docs/providers.md`, `site/docs/providers.html`, `docs/faq.md` ("Why is my agent history shown but not offered?"), `site/docs/faq.html`, `CHANGELOG.md`; regenerate `site/llms-full.txt` with `uv run python scripts/build_llms_full.py`.

- [x] **Step 1: Write the rows and the FAQ entry** (as committed).
- [x] **Step 2: `uv run pytest tests/test_docs_bundle.py -q`** — passes.

### Task 4: Verification on the reference machine

- [x] `uv run pytest -q`, `ruff check`, `ruff format --check`, `mypy src`, `cd web && bun run vitest run && bun run typecheck && bun run lint`.
- [x] `uv run devdoctor scan --provider codex-sessions,claude-code-sessions,opencode-sessions`: buckets and counts match the survey in the spec; nothing is offered below 90 days.
