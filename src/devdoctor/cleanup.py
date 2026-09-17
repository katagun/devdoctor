from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable, Generator
from dataclasses import dataclass
from typing import Literal

from devdoctor.containment import is_reclaimable_worktree, path_is_inside
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
    Refusal,
    RefusalKind,
    Report,
    Risk,
    ShellResult,
    cleanup_action_argv,
    estimated_reclaimable_bytes,
    render_cleanup_action,
)
from devdoctor.units import human_bytes

logger = logging.getLogger(__name__)

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


@dataclass(frozen=True)
class SkippedEntry:
    """One candidate that will not run in this cleanup, and why (spec §4.3).

    Selection-phase skips (dangerous, declined, provider-skip, quit) are decided
    before ``ConfirmRequired`` is yielded, but only resolved into ``EntryResolved``
    later, from ``_iter_execute`` — well after the observer has already seen and
    acted on ``ConfirmRequired``. The presenter needs them on the event itself.
    """

    entry: Entry
    reason: str


@dataclass
class ConfirmRequired:
    approved: list[Entry]
    total_bytes: int
    unknown_entries: int = 0
    # The approved entries in execution order, with what will run (spec §3.2).
    plan: tuple[PlannedEntry, ...] = ()
    # Non-approved candidates, in selection order, with the reason each was skipped.
    skipped: tuple[SkippedEntry, ...] = ()


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


@dataclass(frozen=True)
class PlannedEntry:
    """One approved entry as it will run: the same actions ``_run_actions`` executes."""

    entry: Entry
    actions: tuple[CleanupAction, ...]
    estimate_bytes: int | None

    @property
    def lines(self) -> tuple[str, ...]:
        return tuple(render_cleanup_action(action) for action in self.actions)


@dataclass
class VerifyRequired:
    """Asks whether a worktree is still removable, immediately before it is removed.

    The adapter answers ``None`` to proceed, or a ``Refusal`` to skip the removal.
    """

    entry: Entry


@dataclass
class EntryResolved:
    result: CleanResult


CleanupEvent = PromptRequired | ConfirmRequired | VerifyRequired | ExecuteStep | EntryResolved

# Sees every event before the adapter answers it; presentation only (spec §3.1).
CleanupObserver = Callable[[CleanupEvent], None]


def _notify_observer(on_event: CleanupObserver | None, event: CleanupEvent) -> None:
    """Deliver one event; an observer that raises is logged and can never alter a run."""
    if on_event is None:
        return
    try:
        on_event(event)
    except Exception:
        logger.warning("cleanup observer failed on %s", type(event).__name__, exc_info=True)


# Re-checks an entry against current state: None if it is still removable, else why not.
Verify = Callable[[Entry], Refusal | None]

# The answer when an adapter was given no verifier: never remove what cannot be re-checked.
NO_VERIFIER = Refusal(RefusalKind.UNVERIFIED, "no verifier configured")


def refusal_message(refusal: Refusal) -> str:
    """The skipped entry's message: a real change asks for a rescan, a failed check does not."""
    if refusal.kind is RefusalKind.CHANGED:
        return f"changed since the scan: {refusal.reason}; rescan before cleaning"
    return f"not removed: could not re-check this worktree ({refusal.reason})"


def iter_cleanup_events(report: Report, opts: CleanupOpts) -> Generator[CleanupEvent, object, None]:
    """Pure state machine. Yields events; receives answers via .send().

    - PromptRequired  -> send Choice ('y'/'n'/'a'/'s'/'q')
    - ConfirmRequired -> send bool
    - VerifyRequired  -> send None to proceed, or a Refusal to skip the entry
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
        plan=_build_plan(selections),
        skipped=_build_skipped(selections),
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


def _execution_order(
    selections: list[tuple[Entry, SelectionState]],
) -> list[tuple[Entry, SelectionState]]:
    """Approved reclaimable worktrees first (spec §6.4); otherwise selection order."""
    return sorted(
        selections,
        key=lambda item: not (item[1] == "approved" and is_reclaimable_worktree(item[0])),
    )


def _build_plan(selections: list[tuple[Entry, SelectionState]]) -> tuple[PlannedEntry, ...]:
    return tuple(
        PlannedEntry(
            entry=entry,
            actions=tuple(entry.cleanup_actions()),
            estimate_bytes=entry.reclaimable_bytes,
        )
        for entry, state in _execution_order(selections)
        if state == "approved"
    )


def _build_skipped(selections: list[tuple[Entry, SelectionState]]) -> tuple[SkippedEntry, ...]:
    """Non-approved candidates, in selection order, with why each was skipped."""
    return tuple(
        SkippedEntry(entry=entry, reason=_to_result(entry, state).message or state)
        for entry, state in selections
        if state != "approved"
    )


def _iter_execute(
    selections: list[tuple[Entry, SelectionState]],
) -> Generator[CleanupEvent, object, None]:
    """Run each approved entry's recipe via ExecuteStep yields; resolve every selection.

    Approved reclaimable worktrees run first. An approved entry inside a worktree whose
    removal succeeded in this run is already gone, so it resolves as skipped instead of
    running; if the removal was declined or failed, the entry runs normally (spec §6.4).
    """
    worktrees_first = _execution_order(selections)
    # Resolved before anything runs: a removed directory can no longer be resolved.
    real = {
        entry.id: os.path.realpath(entry.path)
        for entry, state in selections
        if state == "approved" and entry.path is not None
    }
    removed: dict[str, Entry] = {}
    for entry, state in worktrees_first:
        if state != "approved":
            yield EntryResolved(_to_result(entry, state))
            continue
        worktree = None if is_reclaimable_worktree(entry) else _removed_with(entry, real, removed)
        if worktree is not None:
            yield EntryResolved(
                CleanResult(
                    entry_id=entry.id,
                    status="skipped",
                    freed_bytes=0,
                    message=f"removed with worktree {worktree.label}",
                )
            )
            continue
        if is_reclaimable_worktree(entry):
            # Git never re-checks integration, so re-classify right before removal (#110).
            refusal = yield VerifyRequired(entry)
            if refusal is not None:
                assert isinstance(refusal, Refusal)
                yield EntryResolved(
                    CleanResult(
                        entry_id=entry.id,
                        status="skipped",
                        freed_bytes=0,
                        message=refusal_message(refusal),
                    )
                )
                continue
        error_msg, executed = yield from _run_actions(entry)
        if executed and not error_msg and is_reclaimable_worktree(entry):
            removed[real[entry.id]] = entry
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


def _removed_with(entry: Entry, real: dict[str, str], removed: dict[str, Entry]) -> Entry | None:
    """The worktree removed in this run whose path holds ``entry``, if any."""
    path = real.get(entry.id)
    if path is None:
        return None
    return next((owner for root, owner in removed.items() if path_is_inside(path, {root})), None)


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
    verify: Verify | None = None,
    on_event: CleanupObserver | None = None,
) -> list[CleanResult]:
    """Sync adapter over iter_cleanup_events. Preserves the v1 signature and behavior."""
    gen = iter_cleanup_events(report, opts)
    results: list[CleanResult] = []
    try:
        event = next(gen)
        while True:
            _notify_observer(on_event, event)
            if isinstance(event, PromptRequired):
                event = gen.send(prompt_choice(event.entry))
            elif isinstance(event, ConfirmRequired):
                summary = _confirm_summary(event)
                event = gen.send(confirm(summary))
            elif isinstance(event, VerifyRequired):
                event = gen.send(NO_VERIFIER if verify is None else verify(event.entry))
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
    verify: Verify | None = None,
    on_event: CleanupObserver | None = None,
) -> list[CleanResult]:
    """Async adapter over iter_cleanup_events. The web backend uses this."""
    gen = iter_cleanup_events(report, opts)
    results: list[CleanResult] = []
    try:
        event = next(gen)
        while True:
            _notify_observer(on_event, event)
            if isinstance(event, PromptRequired):
                answer = await prompt_choice(event.entry)
                event = gen.send(answer)
            elif isinstance(event, ConfirmRequired):
                summary = _confirm_summary(event)
                event = gen.send(await confirm(summary))
            elif isinstance(event, VerifyRequired):
                event = gen.send(await answer_verify(verify, event.entry))
            elif isinstance(event, ExecuteStep):
                event = gen.send(await run_line(event.argv))
            elif isinstance(event, EntryResolved):
                results.append(event.result)
                event = next(gen)
    except StopIteration:
        pass
    return results


async def answer_verify(verify: Verify | None, entry: Entry) -> Refusal | None:
    """Answer ``VerifyRequired`` off the event loop: verification runs git subprocesses."""
    if verify is None:
        return NO_VERIFIER
    return await asyncio.to_thread(verify, entry)


def _confirm_summary(event: ConfirmRequired) -> str:
    estimate = human_bytes(event.total_bytes)
    summary = f"Execute these {len(event.approved)} entries (~{estimate} estimated"
    if event.unknown_entries:
        summary += f", +{event.unknown_entries} unknown"
    return summary + ")?"


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
