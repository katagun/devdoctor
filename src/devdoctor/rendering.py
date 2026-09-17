from __future__ import annotations

import shutil
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.prompt import Confirm as RichConfirm
from rich.prompt import Prompt
from rich.status import Status
from rich.table import Table
from rich.text import Text

from devdoctor.cleanup import (
    CleanupEvent,
    ConfirmRequired,
    EntryResolved,
    ExecuteStep,
    PlannedEntry,
)
from devdoctor.discovery import ProviderFinished, ProviderStarted, ScanProgressEvent, ScanStarted
from devdoctor.types import (
    Choice,
    CleanResult,
    Confirm,
    DiffReport,
    Entry,
    PromptChoice,
    Report,
    Risk,
)
from devdoctor.units import estimated_bytes, human_bytes, human_bytes_or_unknown

# Every C0 control char (incl. ESC 0x1b and newline) plus DEL. Rich's own
# strip_control_codes intentionally keeps ESC, so we drop these ourselves.
_CONTROL_STRIP = {c: None for c in [*range(0x20), 0x7F]}


def _strip_controls(value: str) -> str:
    return value.translate(_CONTROL_STRIP)


def _safe_cell(value: str) -> Text:
    """Render a filename-derived string as inert text.

    Entry labels, provider names, and recipe hints come from attacker-nameable
    files/dirs. Passed as a plain string, Rich would parse ``[...]`` as markup
    (a malformed tag raises MarkupError and aborts the whole render) and would
    pass raw ANSI/OSC escapes straight to the terminal (screen-clear, title
    spoofing, output forgery). ``Text`` disables markup; stripping control
    chars (ESC included) removes the escape sequences.
    """
    return Text(_strip_controls(value))


def render_report_table(console: Console, report: Report) -> None:
    table = Table(title=f"devdoctor scan — {len(report.entries)} entries", show_lines=False)
    table.add_column("Provider", style="cyan")
    table.add_column("Label", overflow="fold")
    table.add_column("Footprint", justify="right")
    table.add_column("Est. reclaim", justify="right")
    table.add_column("Shared", justify="right")
    table.add_column("Risk", justify="center")
    table.add_column("Stale?", justify="center")
    table.add_column("Recipe hint", overflow="ellipsis")

    term_width = shutil.get_terminal_size((120, 24)).columns
    hint_max = max(20, term_width - 80)

    for e in report.entries:
        table.add_row(
            _safe_cell(e.provider),
            _safe_cell(e.label),
            _human_bytes_or_unknown(e.footprint_bytes),
            _estimated_bytes(e.reclaimable_bytes),
            _human_bytes(e.shared_bytes),
            _risk_label(e.risk),
            _staleness(e.mtime),
            _safe_cell((e.recipe_lines()[0] if e.recipe_lines() else "")[:hint_max]),
        )

    if not report.entries:
        table.add_row("(no entries)", "", "", "", "", "", "", "")

    unknown = report.unknown_reclaimable_entries()
    suffix = f" + {unknown} unknown" if unknown else ""
    table.caption = (
        f"Footprint: {_human_bytes(report.total_footprint_bytes())} · "
        f"estimated reclaimable: ~{_human_bytes(report.total_reclaimable_bytes())}{suffix} · "
        f"shared: {_human_bytes(report.total_shared_bytes())}"
    )
    console.print(table)
    _render_diagnostics(console, report)


# Show at most this many diagnostic lines under the table; the rest collapse
# into a "+N more" note so a pathological scan can't flood the terminal.
_MAX_DIAGNOSTIC_LINES = 5


def _render_diagnostics(console: Console, report: Report) -> None:
    """Print a short, inert note about anything the scan couldn't fully read.

    Diagnostic strings are provider-formatted and can embed attacker-nameable
    paths, so they go through the same control-stripping as table cells.
    """
    if not report.diagnostics:
        return
    console.print(
        Text(
            f"⚠ {len(report.diagnostics)} diagnostic(s) during scan "
            "(some paths skipped, e.g. permission denied):",
            style="yellow",
        )
    )
    for msg in report.diagnostics[:_MAX_DIAGNOSTIC_LINES]:
        console.print(Text(f"  • {_strip_controls(msg)}", style="dim"))
    remaining = len(report.diagnostics) - _MAX_DIAGNOSTIC_LINES
    if remaining > 0:
        console.print(Text(f"  • (+{remaining} more)", style="dim"))


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
        header = Text()
        header.append(_strip_controls(entry.provider), style="bold")
        header.append(
            f" — {_strip_controls(entry.label)}  "
            f"(footprint={_human_bytes_or_unknown(entry.footprint_bytes)}, "
            f"estimated reclaimable={_estimated_bytes(entry.reclaimable_bytes)}, "
            f"risk={_risk_label(entry.risk)})"
        )
        console.print(header)
        recipes = entry.recipe_lines()
        recipe_hint = _strip_controls(recipes[0]) if recipes else "(no cleanup action)"
        console.print(Text(f"  → {recipe_hint}"))
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


_MAX_RUNNING_NAMES = 3
_SNAPSHOT_HINT = (
    'APFS local snapshots can hold freed blocks; see docs "why did my free space not change"'
)


def _group_reasons(reasons: Iterable[str]) -> str:
    """Group repeated reason strings into ``"N reason, M other-reason"``, in first-seen order."""
    counts: dict[str, int] = {}
    for reason in reasons:
        counts[reason] = counts.get(reason, 0) + 1
    return ", ".join(f"{n} {_strip_controls(reason)}" for reason, n in counts.items())


class CleanupPresenter:
    """Every line `devdoctor clean` prints, driven by cleanup and scan events (spec §4).

    Serves the ``--execute`` path only: the preview (dry-run) path renders the report
    table directly and never touches this class.

    It only observes: a failure here is logged by the core and the run continues.
    """

    def __init__(self, console: Console, *, home: Path | None = None) -> None:
        self._console = console
        self._home = home or Path.home()
        self._status: Status | None = None
        self.status_text = ""
        self.plan: tuple[PlannedEntry, ...] = ()
        self._index: dict[str, int] = {}
        self._plan_printed = False
        self._scan_total = 0
        self._scan_done = 0
        self._scan_running: list[str] = []

    # -- scan phase -------------------------------------------------------

    @contextmanager
    def scanning(self) -> Iterator[None]:
        self._start_status("scanning…")
        try:
            yield
        finally:
            self._clear_status()

    def scan_progress(self, event: ScanProgressEvent) -> None:
        if isinstance(event, ScanStarted):
            self._scan_total, self._scan_done, self._scan_running = len(event.providers), 0, []
        elif isinstance(event, ProviderStarted):
            self._scan_running.append(event.name)
        elif isinstance(event, ProviderFinished):
            self._scan_done += 1
            if event.timing.name in self._scan_running:
                self._scan_running.remove(event.timing.name)
        if self._scan_total and self._scan_done == self._scan_total:
            self._set_status("scanning… reconciling")
            return
        text = f"scanning… {self._scan_done}/{self._scan_total} providers"
        if self._scan_running:
            names = ", ".join(self._scan_running[:_MAX_RUNNING_NAMES])
            more = len(self._scan_running) - _MAX_RUNNING_NAMES
            text += f" · running: {names}" + (f" +{more}" if more > 0 else "")
        self._set_status(text)

    # -- cleanup events ---------------------------------------------------

    @contextmanager
    def executing(self) -> Iterator[None]:
        self._start_status("cleaning…")
        try:
            yield
        finally:
            self._clear_status()

    def on_event(self, event: CleanupEvent) -> None:
        if isinstance(event, ConfirmRequired):
            self.plan = event.plan
            self._index = {p.entry.id: i + 1 for i, p in enumerate(event.plan)}
            self._plan_printed = True
            self._print_plan(event)
        elif isinstance(event, ExecuteStep):
            n = self._index.get(event.entry.id, 0)
            self._set_status(f"[{n}/{len(self.plan)}] running: {_strip_controls(event.line)}")
        elif isinstance(event, EntryResolved):
            if event.result.entry_id in self._index:
                self._print_result(event.result)
            # Ids outside the plan are selection-phase skips: already summarised on
            # ConfirmRequired's ``skipped``, or (nothing approved) in summary().
        # PromptRequired and VerifyRequired need no output here.

    def _print_plan(self, event: ConfirmRequired) -> None:
        total = len(event.plan)
        title = f"Cleanup plan — {total} entries, ~{_human_bytes(event.total_bytes)} estimated"
        if event.unknown_entries:
            title += f" (+{event.unknown_entries} unknown)"
        table = Table(title=title, show_lines=False)
        table.add_column("#", justify="right")
        table.add_column("provider", style="cyan")
        table.add_column("risk", justify="center")
        table.add_column("est.", justify="right")
        table.add_column("path", overflow="fold")
        table.add_column("action", overflow="ellipsis")
        for i, planned in enumerate(event.plan, 1):
            lines = planned.lines
            action = lines[0] if lines else "(no cleanup action)"
            if len(lines) > 1:
                action += f" (+{len(lines) - 1} more)"
            table.add_row(
                str(i),
                _safe_cell(planned.entry.provider),
                _risk_label(planned.entry.risk),
                _estimated_bytes(planned.estimate_bytes).lstrip("~"),
                _safe_cell(self._short_path(planned.entry)),
                _safe_cell(action),
            )
        self._console.print(table)
        skipped = _group_reasons(s.reason for s in event.skipped)
        if skipped:
            self._console.print(Text(f"Not in this run: {skipped}", style="dim"))

    def _print_result(self, result: CleanResult) -> None:
        n = self._index[result.entry_id]
        planned = self.plan[n - 1]
        mark = {"ok": "✓", "error": "✗", "skipped": "-"}.get(result.status, "·")
        if result.status == "skipped" and result.message == "advice only; no command executed":
            mark = "·"
        first_line = (result.message or "").splitlines()[0] if result.message else ""
        detail = {
            "ok": f"~{_human_bytes(result.freed_bytes)}" if result.freed_bytes else "done",
            "error": f"failed: {first_line}",
            "skipped": first_line if mark == "·" else f"skipped: {first_line}",
        }.get(result.status, first_line)
        line = Text(f"[{n}/{len(self.plan)}] {mark} ")
        line.append(_strip_controls(planned.entry.provider).ljust(22))
        line.append(_strip_controls(self._short_path(planned.entry)).ljust(40) + "  ")
        line.append(_strip_controls(detail))
        self._console.print(line)

    # -- prompts ------------------------------------------------------------

    def prompt_choice(self, entry: Entry) -> Choice:
        header = Text()
        header.append(_strip_controls(entry.provider), style="bold")
        header.append(
            f" — {_strip_controls(entry.label)}  "
            f"(footprint={_human_bytes_or_unknown(entry.footprint_bytes)}, "
            f"estimated reclaimable={_estimated_bytes(entry.reclaimable_bytes)}, "
            f"risk={_risk_label(entry.risk)})"
        )
        was_active = self._status is not None
        if was_active:
            self._clear_status()
        self._console.print(header)
        recipes = entry.recipe_lines()
        recipe_hint = _strip_controls(recipes[0]) if recipes else "(no cleanup action)"
        self._console.print(Text(f"  → {recipe_hint}"))
        raw = Prompt.ask(
            "[y]es / [n]o / [a]ll-in-provider / [s]kip-provider / [q]uit",
            console=self._console,
            choices=["y", "n", "a", "s", "q"],
            default="n",
            show_choices=False,
        )
        if was_active:
            self._start_status(self.status_text)
        return raw  # type: ignore[return-value]

    def confirm(self, message: str) -> bool:
        was_active = self._status is not None
        if was_active:
            self._clear_status()
        result = RichConfirm.ask(message, console=self._console, default=False)
        if was_active:
            self._start_status(self.status_text)
        return result

    # -- summary --------------------------------------------------------------

    def summary(
        self,
        results: Sequence[CleanResult],
        *,
        free_before: int | None,
        free_after: int | None,
    ) -> None:
        ok = sum(r.status == "ok" for r in results)
        failed = sum(r.status == "error" for r in results)
        skipped = sum(r.status == "skipped" for r in results)
        previewed = sum(r.status == "dry_run" for r in results)
        reclaimed = sum(r.freed_bytes for r in results if r.status == "ok")
        planned = sum(p.estimate_bytes or 0 for p in self.plan)
        counts = f"Done: {ok} ok · {failed} failed · {skipped} skipped"
        if previewed:
            counts += f" · {previewed} previewed"
        self._console.print(
            Text(
                f"{counts} — "
                f"~{_human_bytes(reclaimed)} estimated reclaimed of "
                f"~{_human_bytes(planned)} planned",
                style="bold",
            )
        )
        if not self._plan_printed and skipped:
            skip_messages = (r.message or "skipped" for r in results if r.status == "skipped")
            self._console.print(Text(f"Nothing to clean: {_group_reasons(skip_messages)}"))
        tail = ""
        if free_before is not None and free_after is not None:
            delta = free_after - free_before
            sign = "+" if delta >= 0 else "-"
            tail = (
                f"free space {_human_bytes(free_before)} → {_human_bytes(free_after)} "
                f"({sign}{_human_bytes(abs(delta))}) · "
            )
        self._console.print(Text(f"{tail}recorded: devdoctor history"))
        if (
            free_before is not None
            and free_after is not None
            and reclaimed
            and free_after - free_before < reclaimed / 2
        ):
            self._console.print(Text(_SNAPSHOT_HINT, style="yellow"))

    # -- helpers ---------------------------------------------------------------

    def _short_path(self, entry: Entry) -> str:
        if entry.path is None:
            return entry.label
        text = str(entry.path)
        home = str(self._home)
        return "~" + text[len(home) :] if text == home or text.startswith(home + "/") else text

    def _start_status(self, text: str) -> None:
        """Create and start a ``Status``. Only ``scanning()``/``executing()`` (and the
        prompt/confirm pause-resume) may call this — it's the only place a background
        render thread is spun up."""
        self.status_text = text
        self._status = self._console.status(text)
        self._status.start()

    def _set_status(self, text: str) -> None:
        """Update the status text. Safe to call with no active ``Status`` (e.g. outside
        ``scanning()``/``executing()``): ``status_text`` still reflects the latest
        event, but no background render thread is created."""
        self.status_text = text
        if self._status is not None:
            self._status.update(text)

    def _clear_status(self) -> None:
        if self._status is not None:
            self._status.stop()
            self._status = None


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


_DAYS_PER_MONTH = 30
_DAYS_PER_YEAR = 365

_human_bytes = human_bytes
_human_bytes_or_unknown = human_bytes_or_unknown
_estimated_bytes = estimated_bytes


def _staleness(mtime: float | None) -> str:
    if mtime is None:
        return "—"
    age_days = (datetime.now().timestamp() - mtime) / 86400
    if age_days < 1:
        return "today"
    if age_days < _DAYS_PER_MONTH:
        return f"{int(age_days)}d"
    if age_days < _DAYS_PER_YEAR:
        return f"{int(age_days / _DAYS_PER_MONTH)}mo"
    return f"{age_days / _DAYS_PER_YEAR:.1f}y"
