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
      - DANGEROUS entries are gated BEFORE provider overrides, so 'a' cannot
        silently bypass --allow-dangerous.
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
        raise AssertionError(f"_to_result called with approved entry {entry.id!r}; should be routed to _execute_entry")
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
        risks = {e.risk.value for e in entries}
        risk = risks.pop() if len(risks) == 1 else "mixed"
        lines.append(f"# --- {provider}: {total} bytes freed, risk={risk} ---")
        lines.append(f"# {len(entries)} entr{'y' if len(entries) == 1 else 'ies'}")
        for e in entries:
            lines.append(f"#   [{e.size_bytes} B] {e.label}")
            for cmd in e.recipe:
                lines.append(f"#   {cmd}")
        lines.append("")
    return "\n".join(lines)
