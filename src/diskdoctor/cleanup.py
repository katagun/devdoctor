from __future__ import annotations

import shlex
from collections.abc import Generator
from dataclasses import dataclass
from typing import Literal

from diskdoctor.ports import Shell
from diskdoctor.types import (
    CleanResult,
    CleanupOpts,
    Confirm,
    Entry,
    PromptChoice,
    Report,
    Risk,
    ShellResult,
)

SelectionState = Literal[
    "approved",
    "skipped:user",
    "skipped:provider-skip",
    "skipped:quit",
    "skipped:dangerous",
]


@dataclass
class PromptRequired:
    entry: Entry


@dataclass
class ConfirmRequired:
    approved: list[Entry]
    total_bytes: int


@dataclass
class ExecuteStep:
    entry: Entry
    line: str


@dataclass
class EntryResolved:
    result: CleanResult


CleanupEvent = PromptRequired | ConfirmRequired | ExecuteStep | EntryResolved


def iter_cleanup_events(report: Report, opts: CleanupOpts) -> Generator[CleanupEvent, object, None]:
    """Pure state machine. Yields events; receives answers via .send().

    - PromptRequired  -> send Choice ('y'/'n'/'a'/'s'/'q')
    - ConfirmRequired -> send bool
    - ExecuteStep     -> send ShellResult (adapter runs the shell)
    - EntryResolved   -> advance with next()

    Terminates via StopIteration once every candidate has resolved.
    """
    candidates = _select_candidates(report, opts)

    if not opts.execute:
        for e in candidates:
            yield EntryResolved(
                CleanResult(entry_id=e.id, status="dry_run", freed_bytes=e.size_bytes)
            )
        return

    # Selection phase (may yield PromptRequired for interactive decisions).
    selections = yield from _iter_selection(candidates, opts)

    approved = [e for e, s in selections if s == "approved"]
    if not approved:
        for e, state in selections:
            yield EntryResolved(_to_result(e, state))
        return

    total_bytes = sum(e.size_bytes for e in approved)
    confirmed = yield ConfirmRequired(approved=approved, total_bytes=total_bytes)
    if not confirmed:
        yield from _resolve_aborted(selections)
        return

    yield from _iter_execute(selections)


def _iter_selection(
    candidates: list[Entry], opts: CleanupOpts
) -> Generator[CleanupEvent, object, list[tuple[Entry, SelectionState]]]:
    """Walk candidates, prompting as needed; produce a list of (entry, state) pairs."""
    selections: list[tuple[Entry, SelectionState]] = []
    provider_override: dict[str, str] = {}
    quit_signalled = False

    for entry in candidates:
        auto_state = _auto_state(entry, opts, provider_override, quit_signalled)
        if auto_state is not None:
            selections.append((entry, auto_state))
            continue

        choice = yield PromptRequired(entry)
        state = _apply_choice(choice, entry, provider_override)
        if state == "skipped:quit":
            quit_signalled = True
        selections.append((entry, state))

    return selections


def _auto_state(
    entry: Entry,
    opts: CleanupOpts,
    provider_override: dict[str, str],
    quit_signalled: bool,
) -> SelectionState | None:
    """Return the pre-determined state for an entry, or None if a prompt is required."""
    if quit_signalled:
        return "skipped:quit"
    if entry.risk == Risk.DANGEROUS and not opts.allow_dangerous:
        return "skipped:dangerous"
    override = provider_override.get(entry.provider)
    if override == "all":
        return "approved"
    if override == "skip":
        return "skipped:provider-skip"
    if opts.yes_safe and entry.risk == Risk.SAFE:
        return "approved"
    return None


def _apply_choice(
    choice: object, entry: Entry, provider_override: dict[str, str]
) -> SelectionState:
    """Translate a prompt choice into a selection state; may mutate provider_override."""
    if choice == "y":
        return "approved"
    if choice == "n":
        return "skipped:user"
    if choice == "a":
        provider_override[entry.provider] = "all"
        return "approved"
    if choice == "s":
        provider_override[entry.provider] = "skip"
        return "skipped:provider-skip"
    if choice == "q":
        return "skipped:quit"
    return f"skipped:unknown-choice:{choice}"  # type: ignore[return-value]


def _resolve_aborted(
    selections: list[tuple[Entry, SelectionState]],
) -> Generator[CleanupEvent, object, None]:
    """Emit EntryResolved for every selection after the user declined at final confirm."""
    for e, state in selections:
        if state == "approved":
            yield EntryResolved(
                CleanResult(
                    entry_id=e.id,
                    status="skipped",
                    freed_bytes=0,
                    message="aborted at confirm",
                )
            )
        else:
            yield EntryResolved(_to_result(e, state))


def _iter_execute(
    selections: list[tuple[Entry, SelectionState]],
) -> Generator[CleanupEvent, object, None]:
    """Run each approved entry's recipe via ExecuteStep yields; resolve every selection."""
    for entry, state in selections:
        if state != "approved":
            yield EntryResolved(_to_result(entry, state))
            continue
        error_msg = yield from _run_recipe(entry)
        if error_msg:
            yield EntryResolved(
                CleanResult(entry_id=entry.id, status="error", freed_bytes=0, message=error_msg)
            )
        else:
            yield EntryResolved(
                CleanResult(entry_id=entry.id, status="ok", freed_bytes=entry.size_bytes)
            )


def _run_recipe(entry: Entry) -> Generator[CleanupEvent, object, str | None]:
    """Yield ExecuteStep per recipe line; return error message on failure, None on success."""
    for line in entry.recipe:
        result = yield ExecuteStep(entry=entry, line=line)
        assert isinstance(result, ShellResult)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            return detail or f"exit {result.returncode}"
    return None


def run(
    report: Report,
    *,
    shell: Shell,
    prompt_choice: PromptChoice,
    confirm: Confirm,
    opts: CleanupOpts,
) -> list[CleanResult]:
    """Sync adapter over iter_cleanup_events. Preserves the v1 signature and behavior."""
    gen = iter_cleanup_events(report, opts)
    results: list[CleanResult] = []
    try:
        event = next(gen)
        while True:
            if isinstance(event, PromptRequired):
                event = gen.send(prompt_choice(event.entry))
            elif isinstance(event, ConfirmRequired):
                summary = (
                    f"Execute cleanup for {len(event.approved)} entries, "
                    f"freeing ~{event.total_bytes} bytes?"
                )
                event = gen.send(confirm(summary))
            elif isinstance(event, ExecuteStep):
                argv = shlex.split(event.line)
                event = gen.send(shell.run(argv, check=False))
            elif isinstance(event, EntryResolved):
                results.append(event.result)
                event = next(gen)
    except StopIteration:
        pass
    return results


def _select_candidates(report: Report, opts: CleanupOpts) -> list[Entry]:
    entries = report.entries
    if opts.providers is not None:
        entries = [e for e in entries if e.provider in opts.providers]
    return entries


def _to_result(entry: Entry, state: str) -> CleanResult:
    if state == "approved":
        raise AssertionError(
            f"_to_result called with approved entry {entry.id!r}; should be routed to ExecuteStep"
        )
    reason = state.split(":", 1)[1] if ":" in state else state
    msg = {
        "user": "declined",
        "provider-skip": "provider skipped",
        "quit": "quit before confirm",
        "dangerous": "dangerous (pass --allow-dangerous to include)",
    }.get(reason, reason)
    return CleanResult(entry_id=entry.id, status="skipped", freed_bytes=0, message=msg)


def build_script(report: Report) -> str:
    """Emit a reviewable shell script with every destructive line commented out."""
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
