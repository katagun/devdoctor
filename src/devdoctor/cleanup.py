from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass
from typing import Literal

from devdoctor.ports import Shell
from devdoctor.types import (
    AsyncConfirm,
    AsyncPromptChoice,
    AsyncRunLine,
    CleanResult,
    CleanupAction,
    CleanupOpts,
    Confirm,
    Entry,
    PromptChoice,
    Report,
    Risk,
    ShellResult,
    cleanup_action_argv,
    estimated_reclaimable_bytes,
    render_cleanup_action,
)

_ASCII_SPACE = 0x20  # first printable char; anything below is a C0 control
_ASCII_DEL = 0x7F

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
    unknown_entries: int = 0


@dataclass
class ExecuteStep:
    entry: Entry
    action: CleanupAction

    @property
    def argv(self) -> tuple[str, ...]:
        argv = cleanup_action_argv(self.action)
        if argv is None:
            raise ValueError("advice actions are not executable")
        return argv

    @property
    def line(self) -> str:
        return render_cleanup_action(self.action)


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
                CleanResult(
                    entry_id=e.id,
                    status="dry_run",
                    freed_bytes=e.reclaimable_bytes or 0,
                    message=(
                        "reclaimable bytes are unknown"
                        if e.reclaimable_bytes is None
                        else "byte count is an estimate"
                    ),
                )
            )
        return

    # Selection phase (may yield PromptRequired for interactive decisions).
    selections = yield from _iter_selection(candidates, opts)

    approved = [e for e, s in selections if s == "approved"]
    if not approved:
        for e, state in selections:
            yield EntryResolved(_to_result(e, state))
        return

    total_bytes = estimated_reclaimable_bytes(approved)
    unknown_entries = sum(e.reclaimable_bytes is None for e in approved)
    confirmed = yield ConfirmRequired(
        approved=approved,
        total_bytes=total_bytes,
        unknown_entries=unknown_entries,
    )
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
        error_msg, executed = yield from _run_actions(entry)
        if error_msg:
            yield EntryResolved(
                CleanResult(entry_id=entry.id, status="error", freed_bytes=0, message=error_msg)
            )
        elif not executed:
            yield EntryResolved(
                CleanResult(
                    entry_id=entry.id,
                    status="skipped",
                    freed_bytes=0,
                    message="advice only; no command executed",
                )
            )
        else:
            estimate = entry.reclaimable_bytes
            yield EntryResolved(
                CleanResult(
                    entry_id=entry.id,
                    status="ok",
                    freed_bytes=estimate or 0,
                    message=(
                        "cleanup succeeded; reclaimed bytes were not measured"
                        if estimate is None
                        else "cleanup succeeded; byte count is an estimate"
                    ),
                    bytes_verified=False,
                )
            )


def _run_actions(entry: Entry) -> Generator[CleanupEvent, object, tuple[str | None, bool]]:
    """Yield executable typed actions; advice is deliberately non-executable."""
    executed = False
    for action in entry.cleanup_actions():
        if cleanup_action_argv(action) is None:
            continue
        executed = True
        result = yield ExecuteStep(entry=entry, action=action)
        assert isinstance(result, ShellResult)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            return detail or f"exit {result.returncode}", executed
    return None, executed


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
                summary = _confirm_summary(event)
                event = gen.send(confirm(summary))
            elif isinstance(event, ExecuteStep):
                event = gen.send(shell.run(list(event.argv), check=False))
            elif isinstance(event, EntryResolved):
                results.append(event.result)
                event = next(gen)
    except StopIteration:
        pass
    return results


async def run_async(
    report: Report,
    *,
    run_line: AsyncRunLine,
    prompt_choice: AsyncPromptChoice,
    confirm: AsyncConfirm,
    opts: CleanupOpts,
) -> list[CleanResult]:
    """Async adapter over iter_cleanup_events. The web backend uses this."""
    gen = iter_cleanup_events(report, opts)
    results: list[CleanResult] = []
    try:
        event = next(gen)
        while True:
            if isinstance(event, PromptRequired):
                answer = await prompt_choice(event.entry)
                event = gen.send(answer)
            elif isinstance(event, ConfirmRequired):
                summary = _confirm_summary(event)
                event = gen.send(await confirm(summary))
            elif isinstance(event, ExecuteStep):
                event = gen.send(await run_line(event.argv))
            elif isinstance(event, EntryResolved):
                results.append(event.result)
                event = next(gen)
    except StopIteration:
        pass
    return results


def _confirm_summary(event: ConfirmRequired) -> str:
    summary = (
        f"Execute cleanup for {len(event.approved)} entries, "
        f"estimated reclaimable space ~{event.total_bytes} bytes"
    )
    if event.unknown_entries:
        summary += f" plus {event.unknown_entries} unknown estimate(s)"
    return summary + "?"


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


def _comment_safe(value: str) -> str:
    r"""Neutralize a value so it can't break out of a single-line ``# ...`` comment.

    File and directory names may legally contain newlines (and other control
    characters) on macOS/Linux. Left raw, a name like ``foo\nrm -rf ~`` would
    split ``"\n".join(...)`` into multiple physical lines, leaving the tail as
    an *uncommented*, executable line in the "everything is commented out"
    script. Escape every C0 control char (and DEL) to a visible backslash form
    so the reviewer sees one line and nothing runs unexpectedly.
    """
    out: list[str] = []
    for ch in value:
        code = ord(ch)
        if ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif code < _ASCII_SPACE or code == _ASCII_DEL:
            out.append(f"\\x{code:02x}")
        else:
            out.append(ch)
    return "".join(out)


def build_script(report: Report) -> str:
    """Emit a reviewable shell script with every destructive line commented out."""
    lines: list[str] = [
        "#!/usr/bin/env bash",
        "# DevDoctor disk cleanup script",
        "# All destructive commands are commented out. Review each section,",
        "# uncomment the lines you want to run, then execute this file.",
        "set -euo pipefail",
        "",
    ]
    for provider, entries in report.by_provider().items():
        total = estimated_reclaimable_bytes(entries)
        unknown = sum(e.reclaimable_bytes is None for e in entries)
        risks = {e.risk.value for e in entries}
        risk = risks.pop() if len(risks) == 1 else "mixed"
        estimate = f"~{total} reclaimable bytes"
        if unknown:
            estimate += f" + {unknown} unknown"
        lines.append(f"# --- {_comment_safe(provider)}: {estimate}, risk={risk} ---")
        lines.append(f"# {len(entries)} entr{'y' if len(entries) == 1 else 'ies'}")
        for e in entries:
            footprint = e.footprint_bytes
            size_label = (
                f"{footprint} B footprint" if footprint is not None else "unknown footprint"
            )
            lines.append(f"#   [{size_label}] {_comment_safe(e.label)}")
            for cmd in e.recipe_lines():
                lines.append(f"#   {_comment_safe(cmd)}")
        lines.append("")
    return "\n".join(lines)
