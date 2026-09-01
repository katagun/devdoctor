---
name: devdoctor
description: Use when someone wants to run DevDoctor (the `devdoctor` CLI) to scan this machine for reclaimable disk space (or memory) and produce a report, or to clean up caches. Covers generating a scan report, the safety model, and the cleanup flow.
---

# DevDoctor — scan & report procedure

DevDoctor is a local disk/memory cleanup tool for macOS and Linux. The product
is **DevDoctor**; the installable package and CLI are named **`devdoctor`**.
`scan` is **read-only** (preview) — it never deletes anything.

Run from the repo root with `uv run`, or use an installed `devdoctor` on PATH.

## Generate a report (the main procedure)

1. Get the structured scan (don't parse the Rich table — it truncates when captured):

   ```bash
   uv run devdoctor scan --json > /tmp/dd_report.json
   ```

2. Summarize it — total, per-provider breakdown, and the top entries:

   ```bash
   python3 - <<'PY'
   import json
   d = json.load(open("/tmp/dd_report.json"))
   entries = d.get("entries", [])
   def human(n):
       n=float(n)
       for u in ("B","KB","MB","GB","TB"):
           if n<1024: return f"{n:.1f}{u}"
           n/=1024
       return f"{n:.1f}PB"
   from collections import defaultdict
   prov=defaultdict(lambda:[0,0,set()])
   for e in entries:
       prov[e["provider"]][0]+=e["size_bytes"]; prov[e["provider"]][1]+=1; prov[e["provider"]][2].add(e["risk"])
   total=sum(e["size_bytes"] for e in entries)
   nondanger=sum(e["size_bytes"] for e in entries if e["risk"]!="dangerous")
   print(f"{d.get('hostname','?')} · {d.get('platform','?')} · {len(entries)} entries")
   print(f"TOTAL {human(total)} | non-dangerous {human(nondanger)}\n")
   for p,(sz,c,r) in sorted(prov.items(), key=lambda x:-x[1][0]):
       print(f"{p:<22}{human(sz):>10}  x{c}  {'mixed' if len(r)>1 else next(iter(r))}")
   print("\nTop entries:")
   for e in sorted(entries,key=lambda e:-e["size_bytes"])[:12]:
       print(f"  {human(e['size_bytes']):>9}  [{e['risk']:<11}] {e['provider']:<16} {e['label']}")
   for m in d.get("diagnostics", []): print("  diag:", m)
   PY
   ```

3. Present: total surfaced vs. non-dangerous total, the provider table, the
   biggest wins, and note that nothing was deleted (scan is preview-only).
   `diagnostics` lists paths that couldn't be read (e.g. permission denied).

For a human-readable one-off, `uv run devdoctor scan` prints a Rich table
(sorted by size) — fine in a real terminal, but prefer `--json` when capturing.

## Command reference

```bash
devdoctor scan                       # Rich table of all caches, sorted by size
devdoctor scan --json                # structured JSON (use this for reports)
devdoctor scan --min-size 100M --risk safe,reclaimable   # filters
devdoctor providers                  # registered providers + availability
devdoctor recipe [-o file.sh]        # reviewable, fully-commented-out cleanup script
devdoctor snapshot --note "before"   # save a point-in-time scan
devdoctor diff [--to live]           # compare snapshots (or latest vs. now)
devdoctor serve [--port N] [--no-browser]   # local web UI (needs the `web` extra)
devdoctor -v ...                     # verbose logging (surfaces swallowed errors)
```

Memory side (RAM pressure + top consumers): the web UI has a Memory page; the
CLI focus is disk.

## Safety model (do not bypass)

- **`clean` defaults to preview** — zero prompts, zero shell calls. Nothing runs
  until `--execute`.
- Entries are labelled **safe / reclaimable / dangerous**. **Dangerous** entries
  (e.g. `~/Downloads`, user data) are **skipped** unless `--allow-dangerous`, and
  are usually advice-only (an `echo`, not an `rm`).
- Commands run as **argv lists, never through a shell**; paths are `shlex.quote`d.
- `recipe` emits an all-commented-out script for you to review and uncomment.

## Cleanup flow (only when the user asks to actually reclaim space)

```bash
devdoctor clean                      # preview what would happen
devdoctor clean --execute            # interactive: per-entry prompt + final confirm
devdoctor clean --execute --yes-safe # auto-approve SAFE entries, still confirm
devdoctor clean --execute --allow-dangerous   # include dangerous (rarely wanted)
```

Cleanup is destructive — confirm intent, prefer previewing / the `recipe` script
first, and never pass `--allow-dangerous` without explicit user say-so.
