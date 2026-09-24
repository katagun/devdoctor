# Agent session stores with age-based retention (#84)

**Status:** proposed, awaiting review · **Date:** 2026-09-24 ·
**Related:** [#84](https://github.com/katagun/devdoctor/issues/84),
[#83](https://github.com/katagun/devdoctor/issues/83) (the cache half shipped in
PR #148), [#89](https://github.com/katagun/devdoctor/issues/89) (`--older-than`),
[#79](https://github.com/katagun/devdoctor/issues/79) (worktrees: the other kind of
agent exhaust).

## Problem

Agent transcripts are the user's history, not a cache. Today DevDoctor does not
model them at all, so the coverage scan lists them as unclassified and the user
learns nothing except a directory size. Treating them like a cache (one entry,
`rm -rf`) would be a data-loss hazard; leaving them alone wastes gigabytes that
only grow. The primitive that fits is **age-based retention**: sessions untouched
for N days are offered, everything younger is shown and never offered.

Measured on the reference machine on 2026-09-24:

| Store | Layout | Size | Older than 90 days |
|---|---|---:|---:|
| Codex | `~/.codex/sessions/YYYY/MM/DD/rollout-<ts>-<uuid>.jsonl` (527 files) | 3.2 GB | 118 files, 333 MB |
| Codex indexes | `~/.codex/thread_history_1.sqlite`, `logs_2.sqlite` | 1.2 GB | n/a |
| Claude Code | `~/.claude/projects/<slug>/<uuid>.jsonl` (148) plus `<slug>/<uuid>/` (subagents, tool results) | 1.1 GB | 0 |
| OpenCode | `~/.local/share/opencode/opencode.db`, `session` table (237 rows, `time_updated` in ms) | 3.7 GB | in the database |

`~/.claude/projects/<slug>/memory/` also lives there and is never part of any
session.

## Non-goals

- Deleting anything younger than the retention floor, under any flag.
- Editing a SQLite store in place. A half-written database is worse than a full
  disk; those stores get measured advice, never a write.
- A new CLI flag. `--older-than` (#89) already expresses the cutoff, and the
  "an entry is as young as the youngest thing it deletes" rule makes it select
  whole buckets exactly.

## Design

### One provider family, three providers

Family `agent-sessions`: `codex-sessions`, `claude-code-sessions`,
`opencode-sessions`. Each is a class provider (they need per-file age, not a
path glob) in a new module `devdoctor/providers/agent_sessions.py`, sharing one
helper that turns a list of *session records* into bucket entries.

A session record is `(paths: tuple[Path, ...], mtime: float, bytes: int)`:

- **Codex:** one record per `rollout-*.jsonl` (name checked against the
  pattern; symlinks and anything else are ignored). Age is the file's mtime.
- **Claude Code:** one record per `<slug>/<uuid>.jsonl`, plus the sibling
  `<slug>/<uuid>/` directory when it exists. Age is the newest mtime across
  both (a session with a recent tool result is recent). `memory/`, `*.json`
  and any other name are never records.
- **OpenCode:** records come from a read-only query
  (`sqlite3`, URI `mode=ro`) of `session.time_updated`; each record has no
  paths and no bytes of its own. If the query fails (locked, schema changed),
  the provider falls back to the file-only entry below and adds a diagnostic.

### Entries are age buckets, not sessions

One entry per provider per bucket, buckets fixed at **under 30 days, 30–90,
90–180, 180–365, over 365 days**. A bucket entry has:

- `id` `codex-sessions:90-180d` (stable across scans, so snapshots and diffs
  line up), `path` = the store root (so the table has something to show),
  `label` "Codex sessions untouched 90–180 days · 50 sessions".
- `size_bytes` = the members' allocated bytes (Claude Code: file plus sibling
  directory via `size_many`); `mtime` = the **newest** member, so
  `--older-than 90d` selects exactly the buckets whose every member is at least
  90 days old.
- **Risk and actions by age.** Buckets whose newest member is younger than the
  retention floor (default **90 days**) are `dangerous` with one `AdviceAction`
  ("recent history; DevDoctor never offers it") and `reclaimable_bytes` None.
  Buckets at or beyond the floor are `reclaimable` with one `DeletePathAction`
  per member path (files non-recursive, the Claude Code sibling directory
  recursive), estimate = size. Empty buckets produce no entry.
- The floor is `DEVDOCTOR_SESSION_RETENTION_DAYS` (integer days, default 90,
  values under 30 are clamped to 30 so a typo cannot expose this week's work).
  It moves the risk boundary only; bucket edges never move.

Why buckets and not per-session entries: 527 rows for one tool would drown the
table, and the decision the user makes is "everything older than N", not
"this transcript". Why fixed edges: a bucket's identity has to survive across
scans for history and diffs.

### SQLite stores

`opencode-sessions` always emits one `dangerous`, advice-only entry for the
database file (sized; `-wal`/`-shm` included), whose advice carries the
read-only bucket counts when the query worked: "237 sessions, 120 untouched
over 90 days. OpenCode has no retention setting: delete old sessions in the
app, then run VACUUM to give the space back." `codex-sessions` emits the same
kind of entry for `thread_history_*.sqlite` and `logs_*.sqlite` ("Codex's
thread index and logs; it prunes them itself, VACUUM after"). Never a write.

### Cleanup path

Nothing new in `cleanup.py`: it already runs every executable action of an
entry in order and treats advice as non-executable. Two presentation changes:

- The plan line shows the first command plus "(+N more)" when an entry has
  more than one action (`rendering._print_plan`, and the web `recipeHint`
  gains a count), so a bucket reads "rm -f -- …rollout-2026-01-12….jsonl
  (+117 more)".
- The confirm summary already sums estimates; no change.

A member that vanished between scan and cleanup fails its own `rm -f` quietly
(`-f`), the rest proceed, and the entry reports the error count as today.

### Web UI

No page changes. Bucket entries appear on the Disk page like any other, the
"untouched for" chips (#144) select them by `mtime`, and the wizard runs the
actions.

### Coverage

The stores become classified, so the coverage line rises by their size; nothing
to do.

## Safety review

- Only session records are ever offered: name pattern for Codex, the `<uuid>`
  file-plus-directory pair for Claude Code. `memory/` and unknown names are
  invisible to the provider.
- Symlinks are never followed or offered (`lstat`).
- The running session is always younger than the floor.
- SQLite: read-only URI, no writes, failure degrades to a sized file entry.
- `--allow-dangerous` still offers nothing for the young buckets: their only
  action is advice.

## Testing

- Fixture homes with `os.utime`-dated files: bucket membership at the edges
  (89 vs 90 days), sizes, newest-member `mtime`, risk flips at the floor and
  at an overridden floor, clamped floor, `memory/` and symlinks ignored, the
  Claude Code sibling directory counted and deleted with its file.
- A `sqlite3`-built OpenCode fixture: bucket counts in the advice; a
  fixture the provider cannot open still yields the file entry and a
  diagnostic.
- `clean` end to end with `FakeShell`: `--older-than 90d` selects the old
  buckets only; every member gets its own `rm` call; a young bucket under
  `--allow-dangerous` executes nothing.
- Rendering: the "(+N more)" plan line.

## Rollout

Three PRs, each closing part of the acceptance: `codex-sessions` (files only,
plus the shared bucket helper and the plan-line change), `claude-code-sessions`
(the file-plus-directory record), `opencode-sessions` (the read-only SQLite
path). #84 closes with the third. Docs (`providers.md`, `faq.md` "why is my
history shown but not offered?", changelog) travel with each.

## Open questions for review

1. Is 90 days the right default floor, and is an environment variable the
   right override, or should it be a `devdoctor.toml` / web setting?
2. Should `claude-code-sessions` ship at all in a tool that is mostly run from
   inside Claude Code? The floor makes it safe; the question is taste.
3. Bucket edges: 30 / 90 / 180 / 365, or fewer?
